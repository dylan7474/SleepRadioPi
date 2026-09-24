"""Play the station on the Pi's own sound card (the HiFiBerry MiniAmp).

The MiniAmp has no volume control of its own, so the volume is applied
here, to each ~23 ms slice just before it goes to aplay. Buffers are kept
small so a turn of the knob is heard within about a quarter of a second.

The speaker is a listener like a browser: while it plays, the show runs.
Pausing mutes it at once and leaves; if nobody else is listening the show
ends after the station's grace period, and the next press starts a new one.
"""

from __future__ import annotations

import fcntl
import json
import logging
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from sleepradiopi.audio import pcm
from sleepradiopi.config.atomic import write_atomic

log = logging.getLogger(__name__)

SLICE_FRAMES = 1024          # ~23 ms: how often the volume can change
PIPE_BYTES = 16384           # ~93 ms of audio queued in the pipe to aplay
ALSA_BUFFER_US = 250_000     # aplay's own buffer; smaller risks underruns on a Zero
DB_PER_STEP = 0.5            # volume 100 = full scale, 0 = silent
F_SETPIPE_SZ = 1031          # fcntl.F_SETPIPE_SZ (Linux), missing from older Pythons
SAVE_AFTER_S = 3.0           # save the volume once the knob has been still this long


def gain(volume: int) -> float:
    """Volume 0-100 to a linear gain, in even 0.5 dB steps (0 = silent)."""
    if volume <= 0:
        return 0.0
    return 10 ** ((min(volume, 100) - 100) * DB_PER_STEP / 20)


class SpeakerOutput:
    """An Output (start/write/stop) that plays through aplay."""

    def __init__(self, device: str = "default", volume: int = 30,
                 command: list[str] | None = None) -> None:
        self.command = command or [
            "aplay", "-q", "-D", device, "-t", "raw", "-f", "S16_LE",
            "-r", str(pcm.SAMPLE_RATE), "-c", str(pcm.CHANNELS),
            f"--buffer-time={ALSA_BUFFER_US}",
        ]
        self.volume = volume
        self.enabled = True
        self._running = False            # between the show's start() and stop()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _open(self) -> None:
        self._proc = subprocess.Popen(self.command, stdin=subprocess.PIPE)
        try:
            fcntl.fcntl(self._proc.stdin, F_SETPIPE_SZ, PIPE_BYTES)
        except OSError:
            pass
        log.info("speaker on")

    def _close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.info("speaker off")

    # --- Output protocol (the show thread) -----------------------------------------------

    def start(self) -> None:
        with self._lock:
            self._running = True
            if self.enabled and self._proc is None:
                self._open()

    def write(self, block: np.ndarray) -> None:
        for i in range(0, len(block), SLICE_FRAMES):
            with self._lock:
                proc = self._proc
                g = gain(self.volume)
            if proc is None:
                return
            part = block[i:i + SLICE_FRAMES]
            if g != 1.0:
                part = (part.astype(np.float32) * g).astype(np.int16)
            try:
                proc.stdin.write(part.tobytes())
            except (BrokenPipeError, ValueError, OSError):
                with self._lock:
                    if self._proc is proc:
                        log.error("aplay stopped; reopening the speaker")
                        self._close()
                        if self._running and self.enabled:
                            self._open()
                return

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._close()

    # --- pause ------------------------------------------------------------------------

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self.enabled = enabled
            if not enabled:
                self._close()
            elif self._running and self._proc is None:
                self._open()


class TeeOutput:
    """Send the show to several outputs (the speaker and the MP3 stream)."""

    def __init__(self, *outputs) -> None:
        self.outputs = outputs

    def start(self) -> None:
        for o in self.outputs:
            o.start()

    def write(self, block: np.ndarray) -> None:
        for o in self.outputs:
            o.write(block)

    def stop(self) -> None:
        for o in self.outputs:
            o.stop()


class SpeakerControl:
    """Volume and pause for the speaker, from the knob or the web page.

    The volume is remembered in state_file (saved a few seconds after the
    last change, so turning the knob doesn't write to the card every click).
    Pause isn't remembered: the radio always plays at power-on.
    """

    def __init__(self, speaker: SpeakerOutput, join: Callable[[], None],
                 leave: Callable[[], None], state_file: Path | None = None,
                 default_volume: int = 30) -> None:
        self.speaker = speaker
        self._join, self._leave = join, leave
        self.state_file = state_file
        self.paused = True
        self._lock = threading.Lock()
        self._save_timer: threading.Timer | None = None
        speaker.volume = self._load(default_volume)
        speaker.set_enabled(False)   # silent until play()

    def _load(self, default: int) -> int:
        try:
            return max(0, min(100, int(json.loads(self.state_file.read_text())["volume"])))
        except (AttributeError, OSError, ValueError, KeyError, TypeError):
            return default

    def _save(self) -> None:
        if self.state_file is not None:
            write_atomic(self.state_file, json.dumps({"volume": self.speaker.volume}))

    @property
    def volume(self) -> int:
        return self.speaker.volume

    def set_volume(self, volume: int) -> None:
        with self._lock:
            self.speaker.volume = max(0, min(100, int(volume)))
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(SAVE_AFTER_S, self._save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def step(self, delta: int) -> None:
        self.set_volume(self.speaker.volume + delta)

    def play(self) -> None:
        with self._lock:
            if not self.paused:
                return
            self.paused = False
            self.speaker.set_enabled(True)
        log.info("speaker: play")
        self._join()

    def pause(self) -> None:
        with self._lock:
            if self.paused:
                return
            self.paused = True
            self.speaker.set_enabled(False)
        log.info("speaker: pause")
        self._leave()

    def toggle(self) -> None:
        if self.paused:
            self.play()
        else:
            self.pause()

    def status(self) -> dict:
        return {"volume": self.speaker.volume, "playing": not self.paused}
