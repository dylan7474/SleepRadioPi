"""HTTP front end: the radio page, the MP3 stream, and a JSON status feed.

Plain stdlib http.server -- a handful of listeners on a home network needs
nothing more. No auth: meant for a trusted LAN only.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from sleepradiopi.broadcast.station import Station
from sleepradiopi.config import backup
from sleepradiopi.config.settings import save_setting
from sleepradiopi.config.power import can_power_off, request_power_off

from .stream import Mp3Output

log = logging.getLogger(__name__)

PAGE = (Path(__file__).parent / "page.html").read_bytes()
IDLE_CLOSE_S = 30  # close a stream connection that has had no audio for this long
MAX_SETTINGS_BYTES = 64 * 1024
# Set where something restarts the station when it exits (init's respawn on the
# appliance image, systemd's Restart= on Raspberry Pi OS). Without it, e.g. on
# a desktop, loaded settings that need a restart wait for the next start.
RESTART_ENV = "SLEEPRADIOPI_SUPERVISED"
RESTART_EXIT = 75  # EX_TEMPFAIL: "on-failure" restarts it too


def _restart_soon(speaker) -> None:
    """Exit shortly (after the reply has gone) so the supervisor restarts us."""
    def go():
        time.sleep(1)
        log.info("restarting to apply the loaded settings")
        if speaker is not None:
            speaker.save_now()
        os._exit(RESTART_EXIT)
    threading.Thread(target=go, daemon=True).start()


def make_handler(station: Station, output: Mp3Output, speaker=None,
                 config_file: Path | None = None, announcer=None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # keep stream polling out of the journal
            if not self.path.startswith("/api/"):
                log.info("%s %s", self.address_string(), fmt % args)

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser went away mid-reply; nothing to do

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(PAGE, "text/html; charset=utf-8")
            elif path == "/api/status":
                status = station.status()
                if speaker is not None:
                    status["speaker"] = speaker.status()
                status["can_power_off"] = can_power_off()
                self._send(json.dumps(status).encode(), "application/json")
            elif path == "/api/settings" and config_file is not None:
                self._save_settings()
            elif path == "/api/artists":
                self._send(json.dumps({"artist": station.artist, "station_name": station.builder.station,
                                       "artists": station.artists()}).encode(), "application/json")
            elif path == "/stream":
                self._stream()
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/power":
                self._power()
            elif path == "/api/skip":
                self.rfile.read(int(self.headers.get("Content-Length", 0)))  # no body needed
                self._send(json.dumps({"skipped": station.skip()}).encode(), "application/json")
            elif path == "/api/speaker" and speaker is not None:
                self._speaker()
            elif path == "/api/settings" and config_file is not None:
                self._load_settings()
            elif path == "/api/knob" and speaker is not None:
                self._knob()
            elif path == "/api/station":
                self._station()
            else:
                self.send_error(404)

        def _power(self) -> None:
            """/api/power: shut the radio down. Saves the volume and silences
            the speaker first, so it goes quiet at once."""
            self.rfile.read(int(self.headers.get("Content-Length", 0)))  # no body needed
            if not can_power_off():
                self.send_error(404)
                return
            log.info("shutdown requested from %s", self.address_string())
            if speaker is not None:
                speaker.save_now()
                speaker.pause()
            ok = request_power_off()
            self._send(json.dumps({"shutting_down": ok}).encode(), "application/json")

        def _save_settings(self) -> None:
            """GET /api/settings: the settings as a file to download."""
            data = backup.export(config_file, speaker.volume if speaker is not None else None)
            body = (json.dumps(data, indent=2) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition",
                             f'attachment; filename="sleepradio-settings-{time.strftime("%Y-%m-%d")}.json"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _load_settings(self) -> None:
            """POST /api/settings with a saved settings file as the body.
            Volume, mono and EQ change at once; anything else restarts the
            station (if it's supervised). Replies {"ok", "restarting"} or
            {"error"} with status 400."""
            length = int(self.headers.get("Content-Length", 0))
            try:
                if length > MAX_SETTINGS_BYTES:
                    raise backup.BadSettings("that file is far too big to be a settings file")
                try:
                    data = json.loads(self.rfile.read(length))
                except ValueError:
                    raise backup.BadSettings("this isn't a Sleep Radio settings file") from None
                settings, volume = backup.parse(data)
            except backup.BadSettings as e:
                body = json.dumps({"error": str(e)}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            changed = backup.apply(config_file, settings)     # before the live ones save theirs
            if "broadcast_artist" in changed:
                station.set_artist(settings["broadcast_artist"])
            if speaker is not None:
                if "speaker_mono" in settings:
                    speaker.set_mono(settings["speaker_mono"])
                if "speaker_eq" in settings:
                    speaker.set_eq(settings["speaker_eq"])
                if "speaker_highpass_hz" in settings:
                    speaker.set_highpass(settings["speaker_highpass_hz"])
                if volume is not None:
                    if volume != speaker.volume:
                        changed.add("volume")
                    speaker.set_volume(volume)
                    speaker.save_now()
            needs_restart = bool(changed - backup.LIVE - {"volume"})
            restarting = needs_restart and bool(os.environ.get(RESTART_ENV))
            log.info("settings loaded from %s; changed: %s", self.address_string(),
                     ", ".join(sorted(changed)) or "nothing")
            self._send(json.dumps({"ok": True, "changed": sorted(changed),
                                   "needs_restart": needs_restart,
                                   "restarting": restarting}).encode(), "application/json")
            if restarting:
                _restart_soon(speaker)

        def _station(self) -> None:
            """/api/station {"artist": "The Beatles" | null}: artist radio (only
            that artist, and the DJ says "Beatles Radio"), or everything. Saved."""
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                artist = body["artist"]
                if artist is not None and (not isinstance(artist, str) or len(artist) > 200):
                    raise ValueError("artist must be a name or null")
            except (ValueError, TypeError, KeyError, AttributeError):
                self.send_error(400)
                return
            found = station.set_artist(artist.strip() if artist else None)
            if config_file is not None:
                save_setting(config_file, "broadcast_artist", station.artist)
            self._send(json.dumps({"found": found, "artist": station.artist,
                                   "station_name": station.builder.station}).encode(), "application/json")

        def _knob(self) -> None:
            """/api/knob {"press": "short" | "long"}: the knob's switch, from the
            page (to try it without the hardware). Short = pause/play, long =
            say the radio's address."""
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                press = body.get("press")
                if press not in ("short", "long"):
                    raise ValueError("press must be short or long")
            except (ValueError, TypeError, AttributeError):
                self.send_error(400)
                return
            if press == "short":
                speaker.toggle()
                done = True
            else:
                done = announcer.speak() if announcer is not None else False
            self._send(json.dumps({"press": press, "done": done, **speaker.status()}).encode(),
                       "application/json")

        def _speaker(self) -> None:
            """/api/speaker with a JSON body: {"volume": 0-100}, {"step": n},
            {"pause": true | false | "toggle"}, {"sleep": minutes (0 = off)},
            {"mono": true | false} or
            {"eq": {"bass": dB, "mid": dB, "treble": dB}} (any of the three),
            {"highpass": Hz} (the low cut; 0 = off) or
            {"test": "bass" | "sweep" | "pink" | "left" | "right" | "phase" | "stop"}
            (a test sound on the speaker; see audio/testsignal.py).
            Replies with the speaker's status."""
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if "volume" in body:
                    speaker.set_volume(int(body["volume"]))
                if "step" in body:
                    speaker.step(int(body["step"]))
                if "mono" in body:
                    if not isinstance(body["mono"], bool):
                        raise ValueError("mono must be true or false")
                    speaker.set_mono(body["mono"])
                if "eq" in body:
                    eq = body["eq"]
                    if not isinstance(eq, dict) or not all(
                            k in ("bass", "mid", "treble") and isinstance(v, (int, float))
                            and not isinstance(v, bool) for k, v in eq.items()):
                        raise ValueError("eq must map bass/mid/treble to numbers")
                    speaker.set_eq(eq)
                if "highpass" in body:
                    hz = body["highpass"]
                    if isinstance(hz, bool) or not isinstance(hz, (int, float)) or not 0 <= hz <= 300:
                        raise ValueError("highpass must be 0-300 Hz")
                    speaker.set_highpass(hz)
                if "sleep" in body:
                    minutes = body["sleep"]
                    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) \
                            or not 0 <= minutes <= 600:
                        raise ValueError("sleep must be 0-600 minutes")
                    speaker.set_sleep(minutes)
                if "test" in body:
                    if body["test"] == "stop":
                        speaker.stop_test()
                    elif isinstance(body["test"], str):
                        speaker.start_test(body["test"])   # ValueError if unknown
                    else:
                        raise ValueError("test must be a name")
                if body.get("pause") == "toggle":
                    speaker.toggle()
                elif body.get("pause") is True:
                    speaker.pause()
                elif body.get("pause") is False:
                    speaker.play()
            except (ValueError, TypeError, AttributeError, OverflowError):
                self.send_error(400)
                return
            self._send(json.dumps(speaker.status()).encode(), "application/json")

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            q = output.add_client()
            station.listener_joined()
            try:
                while True:
                    chunk = q.get(timeout=IDLE_CLOSE_S)
                    if chunk is None:
                        break
                    self.wfile.write(chunk)
            except (queue.Empty, BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            finally:
                output.remove_client(q)
                station.listener_left()

    return Handler


def serve(station: Station, output: Mp3Output, port: int, speaker=None,
          config_file: Path | None = None, announcer=None) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port),
                                 make_handler(station, output, speaker, config_file, announcer))
    server.daemon_threads = True
    log.info("Sleep Radio on http://0.0.0.0:%d/", port)
    server.serve_forever()
