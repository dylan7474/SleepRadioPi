# SleepRadioPi

A **Broadcast Radio** station on a Raspberry Pi: an auto-DJ that plays your
local music with an offline text-to-speech presenter between tracks —
back-announcements and intros, time checks, station idents, jingles, and
news bulletins on the hour and half past. Open the Pi's web page on any
device on your home network and it plays like a radio station; a physical
bedside version (amp, speakers, buttons, small display) is next.

This is a **from-scratch Python reimplementation** of the Broadcast mode of
[SleepRadio](https://github.com/dylan7474/SleepRadio), an Android app. Its
logic (track selection, DJ scripts, time checks, news, loudness levelling,
edge-silence trim, voice EQ) is ported closely, with the Android app's unit
test cases ported alongside. See [`docs/SCOPE.md`](docs/SCOPE.md).

Status: **the station works** — on a Pi Zero 2 W, streaming to a browser.
See [`docs/ROADMAP.md`](docs/ROADMAP.md) for what's next and
[`docs/PI_SETUP.md`](docs/PI_SETUP.md) for setting up a Pi (development
happens on a desktop; the Pi is reached over SSH).

## Listening

```bash
./scripts/deploy.sh                 # on the desktop: sync to the Pi, run the tests there
./scripts/install_service.sh        # on the Pi, once: start the station at boot
```

Then open **http://sleepradiopi.local/** and press *Tune in*. The show starts
when the first listener connects (welcome, a short jingle, the first track)
and goes off air 30 seconds after the last one leaves. Settings live in
`~/.config/sleepradiopi/config.json` on the Pi (created on first run).

Music goes in `~/media/music/<Artist>/<Album>/`, jingles in `~/media/jingles/`,
and voice packs (`model.onnx`, `tokens.txt`, `espeak-ng-data/` — the same
files SleepRadio uses) in `voices/<name>/`.

## Target hardware

- Raspberry Pi (any model with I2S/HAT support for the amp)
- A HiFiBerry amp + speakers, output via ALSA
- A small LCD (character or graphic — display driver is behind an
  abstraction so the exact panel is a config choice, not a code fork)
- A handful of physical buttons (GPIO), for source-select / play-pause /
  skip / volume / sleep-timer

## Why Python

The Pi ecosystem for GPIO buttons and small LCDs is overwhelmingly
Python-first (`gpiozero`, `luma.lcd`/`RPLCD`), and the one piece of SleepRadio
that has to carry over byte-for-byte — the on-device cloned TTS voice via
`sherpa-onnx` — has a first-class Python binding that runs unchanged on
Raspberry Pi ARM. See `docs/SCOPE.md` for the full stack rationale.

## License

GPL-3.0-or-later — see [`NOTICE`](NOTICE) for why (short version: the offline
TTS engine statically links eSpeak-NG, which is GPL).

## Layout

```
sleepradiopi/
  broadcast/   The station: show clock, DJ scripts, track selection, news, library scan
  audio/       PCM plumbing via ffmpeg: decode, loudness scan, voice EQ, levelling
  tts/         sherpa-onnx voice, run in a recycled worker process
  web/         MP3 stream + the listen-in page + /api/status
  config/      Settings (JSON)
  io/          Physical buttons + display (not yet built)
  playback/    Other sources (deferred: Broadcast is the focus)
scripts/       deploy.sh, install_service.sh, smoke_test_audio.py, dev_web.py
docs/          SCOPE.md, ROADMAP.md, PI_SETUP.md
voices/        (git-ignored) voice packs — never committed
tests/
```

## Pi Zero 2 W: memory is the limit

A neural voice is the heaviest part, and ~464 MB (after freeing the GPU's
reservation) only fits **one** voice alongside the stream. So the DJ and the
newsreader share a voice (`news_voice: "same"`), text is synthesised a
clause at a time, and the TTS worker process is recycled when it passes
200 MB (its buffers grow and never shrink). See `sleepradiopi/tts/worker.py`
and the "Lessons" section of `docs/PI_SETUP.md`.
