"""The volume knob: a rotary encoder with a push switch.

The kernel does the GPIO work (config.txt on the Pi):
  dtoverlay=rotary-encoder,pin_a=17,pin_b=27,relative_axis=1
  dtoverlay=gpio-key,gpio=22,keycode=164,label="PLAYPAUSE"
Both show up as /dev/input/event* devices, read here without extra
libraries: each click of the knob is a relative-axis event (+1/-1) and the
push is a key press. Any relative axis or key works, so a different encoder
or button needs no code change.
"""

from __future__ import annotations

import logging
import os
import select
import struct
import threading
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

# struct input_event: struct timeval (two longs), __u16 type, __u16 code, __s32 value
EVENT = struct.Struct("llHHi")
EV_KEY, EV_REL = 1, 2
KEY_DOWN = 1
RESCAN_S = 10.0   # look for new input devices (modules can load after we start)


def handle(data: bytes, on_turn: Callable[[int], None], on_press: Callable[[], None]) -> None:
    """Dispatch every complete event in data."""
    for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
        _, _, etype, _, value = EVENT.unpack_from(data, i)
        if etype == EV_REL and value:
            on_turn(value)
        elif etype == EV_KEY and value == KEY_DOWN:
            on_press()


class Knob:
    def __init__(self, on_turn: Callable[[int], None], on_press: Callable[[], None],
                 devices: Path = Path("/dev/input")) -> None:
        self.on_turn, self.on_press = on_turn, on_press
        self.devices = devices
        self._fds: dict[str, int] = {}

    def start(self) -> None:
        threading.Thread(target=self._run, name="knob", daemon=True).start()

    def _rescan(self) -> None:
        for path in sorted(self.devices.glob("event*")):
            if str(path) in self._fds:
                continue
            try:
                self._fds[str(path)] = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                log.info("knob: listening to %s", path)
            except OSError as e:
                log.warning("knob: can't open %s: %s", path, e)
                self._fds[str(path)] = -1   # don't retry every rescan

    def _run(self) -> None:
        next_scan = 0.0
        while True:
            if time.monotonic() >= next_scan:
                self._rescan()
                next_scan = time.monotonic() + RESCAN_S
            fds = [fd for fd in self._fds.values() if fd >= 0]
            if not fds:
                time.sleep(RESCAN_S)
                continue
            ready, _, _ = select.select(fds, [], [], RESCAN_S)
            for fd in ready:
                try:
                    data = os.read(fd, EVENT.size * 64)
                except BlockingIOError:
                    continue
                except OSError:   # device went away
                    data = b""
                if not data:
                    os.close(fd)
                    self._fds = {k: v for k, v in self._fds.items() if v != fd}
                    continue
                try:
                    handle(data, self.on_turn, self.on_press)
                except Exception:
                    log.exception("knob: handler failed")
