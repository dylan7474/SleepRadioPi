import os
import time
from pathlib import Path

import numpy as np

from sleepradiopi.audio import speaker as speaker_mod
from sleepradiopi.audio.speaker import SpeakerControl, SpeakerOutput, gain
from sleepradiopi.io.knob import EV_KEY, EV_REL, EVENT, Knob, handle


def _event(etype: int, value: int, code: int = 0) -> bytes:
    return EVENT.pack(0, 0, etype, code, value)


def _wait(cond, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_gain_curve() -> None:
    assert gain(0) == 0.0
    assert gain(100) == 1.0
    assert abs(20 * np.log10(gain(98)) - -1.0) < 1e-9
    assert gain(150) == 1.0 and gain(-5) == 0.0


def _speaker(tmp_path: Path) -> tuple[SpeakerOutput, Path]:
    out = tmp_path / "played.raw"
    return SpeakerOutput(command=["sh", "-c", f"cat >> {out}"]), out


def test_speaker_plays_scaled_audio_and_stops_when_paused(tmp_path: Path) -> None:
    spk, out = _speaker(tmp_path)
    block = np.full((3000, 2), 10000, dtype=np.int16)
    spk.volume = 100
    spk.start()
    spk.write(block)
    spk.volume = 0
    spk.write(block)
    spk.set_enabled(False)
    spk.write(block)          # paused: dropped
    spk.stop()
    played = np.frombuffer(out.read_bytes(), dtype=np.int16).reshape(-1, 2)
    assert len(played) == 6000
    assert (played[:3000] == 10000).all() and (played[3000:] == 0).all()


def test_control_joins_once_and_remembers_volume(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(speaker_mod, "SAVE_AFTER_S", 0.05)
    spk, _ = _speaker(tmp_path)
    calls = []
    state = tmp_path / "state" / "speaker.json"
    ctl = SpeakerControl(spk, lambda: calls.append("join"), lambda: calls.append("leave"),
                         state_file=state, default_volume=40)
    assert ctl.status() == {"volume": 40, "playing": False}
    ctl.play(); ctl.play(); ctl.toggle(); ctl.toggle()
    assert calls == ["join", "leave", "join"]
    ctl.set_volume(250)
    assert ctl.volume == 100
    ctl.step(-7)
    assert _wait(lambda: state.exists() and '"volume": 93' in state.read_text())
    again = SpeakerControl(spk, lambda: None, lambda: None, state_file=state, default_volume=40)
    assert again.volume == 93


def test_handle_events() -> None:
    turns, presses = [], []
    data = _event(EV_REL, 1) + _event(EV_REL, -1) + _event(EV_KEY, 1, 164) + _event(EV_KEY, 0, 164)
    handle(data + b"\x00" * 5, turns.append, lambda: presses.append(1))
    assert turns == [1, -1] and presses == [1]


def test_knob_reads_input_devices(tmp_path: Path) -> None:
    fifo = tmp_path / "event0"
    os.mkfifo(fifo)
    turns, presses = [], []
    Knob(turns.append, lambda: presses.append(1), devices=tmp_path).start()
    assert _wait(lambda: True)
    fd = os.open(fifo, os.O_WRONLY)   # blocks until the knob has opened it
    os.write(fd, _event(EV_REL, 1) + _event(EV_REL, 1) + _event(EV_KEY, 1))
    assert _wait(lambda: turns == [1, 1] and presses == [1])
    os.close(fd)
