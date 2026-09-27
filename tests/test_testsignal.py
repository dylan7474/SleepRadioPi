import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from sleepradiopi.audio.eq import Equalizer
from sleepradiopi.audio.speaker import SpeakerControl, SpeakerOutput
from sleepradiopi.audio.testsignal import LEVEL, TestSignal
from sleepradiopi.web.server import make_handler

RATE = 44_100


def _freq(x: np.ndarray) -> float:
    """Frequency of a short stretch of sine, from its zero crossings."""
    s = np.signbit(x)
    crossings = np.nonzero(s[1:] != s[:-1])[0]
    return (len(crossings) - 1) / 2 / ((crossings[-1] - crossings[0]) / RATE)


def test_sweep_follows_its_log_curve_and_reports_the_frequency() -> None:
    sig = TestSignal("bass", RATE, 2)
    x = sig.next(sig.total)[:, 0]
    assert sig.done
    assert np.max(np.abs(x)) <= LEVEL * 32767 + 1
    for frac in (0.1, 0.5, 0.9):
        centre = int(frac * sig.total)
        want = 40 * (600 / 40) ** frac
        assert abs(_freq(x[centre - 2000:centre + 2000]) / want - 1) < 0.03
    half = TestSignal("bass", RATE, 2)
    half.next(half.total // 2)
    assert abs(half.hz() - 40 * (600 / 40) ** 0.5) < 1
    assert abs(x[0]) < 1 and abs(x[-1]) < 1                           # faded: no clicks


def test_pink_noise_falls_3_db_per_octave() -> None:
    sig = TestSignal("pink", RATE, 2)
    x = sig.next(sig.total)[:, 0].astype(float)
    power = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    band = lambda lo: power[(f >= lo) & (f < 2 * lo)].sum()
    drop = 10 * np.log10(band(1000) / band(200))                        # an octave-band's energy
    assert abs(drop) < 1                                                # ~equal per octave
    assert sig.hz() is None and not sig.next(100).any()                 # silent after the end


def test_speaker_plays_the_test_raw_then_goes_back_to_the_show(tmp_path: Path) -> None:
    out = tmp_path / "played.raw"
    spk = SpeakerOutput(command=["sh", "-c", f"cat >> {out}"], mono=True,
                        eq=Equalizer(RATE, 2, {"bass": -12}, highpass=300))
    ctl = SpeakerControl(spk, lambda: None, lambda: None)
    spk.volume = 100
    spk.start()
    ctl.start_test("pink")
    assert not ctl.paused and ctl.status()["test"]["label"] == "Pink noise"
    sig = spk.test
    show = np.full((1024, 2), 1234, dtype=np.int16)
    ref = TestSignal("pink", RATE, 2)
    while spk.test is not None:
        spk.write(show)
    assert ctl.status()["test"] is None
    spk.write(show)
    spk.stop()
    played = np.frombuffer(out.read_bytes(), dtype=np.int16).reshape(-1, 2).astype(int)
    want = ref.next(sig.total)
    assert np.abs(played[:sig.total] - want).max() <= 1     # untouched by mono/EQ/low cut
    assert (played[-1024:] != 1234).any()                   # the show is through the EQ again


def test_pause_or_stop_ends_the_test(tmp_path: Path) -> None:
    spk = SpeakerOutput(command=["sh", "-c", "cat > /dev/null"])
    ctl = SpeakerControl(spk, lambda: None, lambda: None)
    ctl.start_test("sweep")
    ctl.stop_test()
    assert spk.test is None
    ctl.start_test("bass")
    ctl.pause()
    assert spk.test is None
    with pytest.raises(ValueError):
        ctl.start_test("loud")


def test_web_api_starts_and_stops_a_test(tmp_path: Path) -> None:
    class FakeStation:
        def status(self):
            return {"on_air": True}
    spk = SpeakerOutput(command=["sh", "-c", "cat > /dev/null"])
    ctl = SpeakerControl(spk, lambda: None, lambda: None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FakeStation(), None, ctl))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(body):
        req = urllib.request.Request(base + "/api/speaker", data=json.dumps(body).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    try:
        t = post({"test": "bass"})["test"]
        assert t["kind"] == "bass" and t["duration_s"] == 24 and t["hz"] == 40
        assert post({"test": "stop"})["test"] is None
        for bad in ({"test": "loud"}, {"test": 3}):
            with pytest.raises(urllib.error.HTTPError) as err:
                post(bad)
            assert err.value.code == 400
    finally:
        httpd.shutdown()
