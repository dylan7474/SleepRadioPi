"""HTTP front end: the radio page, the MP3 stream, and a JSON status feed.

Plain stdlib http.server -- a handful of listeners on a home network needs
nothing more. No auth: meant for a trusted LAN only.
"""

from __future__ import annotations

import json
import logging
import queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from sleepradiopi.broadcast.station import Station

from .stream import Mp3Output

log = logging.getLogger(__name__)

PAGE = (Path(__file__).parent / "page.html").read_bytes()
IDLE_CLOSE_S = 30  # close a stream connection that has had no audio for this long


def make_handler(station: Station, output: Mp3Output):
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
                self._send(json.dumps(station.status()).encode(), "application/json")
            elif path == "/stream":
                self._stream()
            else:
                self.send_error(404)

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


def serve(station: Station, output: Mp3Output, port: int) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(station, output))
    server.daemon_threads = True
    log.info("Sleep Radio on http://0.0.0.0:%d/", port)
    server.serve_forever()
