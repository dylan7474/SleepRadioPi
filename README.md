# SleepRadioPi

A standalone bedside "sleep radio" appliance for the Raspberry Pi: local
music, audiobooks, internet radio, and a self-hosted **Broadcast Radio**
auto-DJ with an offline text-to-speech presenter, layered with two ambient
channels (procedural coloured noise + binaural beats) and a fading sleep
timer. Controlled entirely by physical buttons and a small LCD — no phone,
no touchscreen, no app.

This is a **from-scratch Python reimplementation** of the ideas and audio
algorithms in [SleepRadio](https://github.com/dylan7474/SleepRadio), an
Android app, retargeted at a headless Pi + amp + speakers setup. See
[`docs/SCOPE.md`](docs/SCOPE.md) for what carries over from that project,
what's being rebuilt, and why.

Status: **early scaffolding** — architecture and module layout only, no
working audio yet. See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the build
order.

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
  audio/       Ambient mixer: noise generator, binaural beat generator
  playback/    Local files, audiobooks, internet radio streaming
  broadcast/   Auto-DJ: track selection, DJ script text, jingle scheduling
  tts/         sherpa-onnx voice pack loading + synthesis
  io/          Physical buttons (gpiozero) + LCD display driver
  config/      Settings persistence (paths, presets, voice, chattiness, ...)
docs/          SCOPE.md, ROADMAP.md, hardware notes
voices/        (git-ignored) imported voice packs — never committed
tests/
```
