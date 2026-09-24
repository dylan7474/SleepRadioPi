# SleepRadioPi

A **bedside radio station** on a Raspberry Pi: an auto-DJ that plays your
local music with an offline text-to-speech presenter between tracks —
back-announcements and intros, 70s-style DJ hooks, station idents, jingles,
and (when it's online) time checks and news bulletins. Plug it in and it's
on air through its own speaker; a single knob sets the volume and pauses.
It also streams to a web page on your home network.

This is a **from-scratch Python reimplementation** of the Broadcast mode of
[SleepRadio](https://github.com/dylan7474/SleepRadio), an Android app. Its
logic (track selection, DJ scripts, time checks, news, loudness levelling,
edge-silence trim, voice EQ) is ported closely, with the Android app's unit
test cases ported alongside. See [`docs/SCOPE.md`](docs/SCOPE.md).

**Status:** the station runs on a Pi Zero 2 W, starts at power-up, plays
through the sound card and has been tested with pulled plugs and with no
network. The HiFiBerry MiniAmp and the knob are being fitted; see
[`docs/ROADMAP.md`](docs/ROADMAP.md).

## How it behaves

- **Power on and it plays.** Within about 40 seconds of power-up the show
  starts ("Hello, and welcome to Sleep Radio...") through the MiniAmp; most
  of that is the voice loading. No app, no phone, no button press.
- **One knob.** Turn for volume (0–100 in 0.5 dB steps; the level is
  remembered). Press to pause; press again within 30 seconds to carry on
  live, or later to start a fresh show.
- **Offline is normal.** A Pi has no battery-backed clock, so without the
  internet it can't know the time. Until the clock has been set from the
  internet (NTP) since power-up, the DJ **doesn't say the time, greets with
  "Hello" rather than "Good evening", and there's no news**; hooks, idents,
  track intros and jingles carry on. When Wi-Fi comes back, the clock is set
  within seconds and time checks and news return. (A DS3231 real-time clock
  module is being added so the time is known offline too.)
- **Pull the plug any time.** On the appliance image the system and the
  music are read-only, and settings are saved atomically (temp file, fsync,
  rename), so a power cut can't leave a half-written file.

## Hardware

| Part | Notes |
|---|---|
| Raspberry Pi Zero 2 W | Any Pi with a 40-pin header works; the Zero 2 W is the target (and the tight one: see memory, below). |
| HiFiBerry MiniAmp | 2 × 3 W class-D amp, powered from the Pi's 5 V. No volume control of its own: the station does it in software. |
| Speaker(s) | 4–8 Ω. |
| Rotary encoder with push switch | Volume + pause. A bare encoder or a KY-040-style module. |
| DS3231 RTC module (optional) | Keeps the time with no network. |
| 5 V supply, **2.5 A or more** | The amp draws from the Pi's 5 V. |

### Wiring

Solder a **full 2×20 header** on the Pi: the MiniAmp is a pHAT that plugs
onto all 40 pins. It covers the pins the knob and RTC need, so either solder
their wires to the underside of the Pi's header, or put a stacking header /
GPIO extender between the Pi and the amp.

| Use | GPIO | Header pin |
|---|---|---|
| MiniAmp: I2S bit clock | GPIO18 | 12 |
| MiniAmp: I2S word clock | GPIO19 | 35 |
| MiniAmp: I2S data | GPIO21 | 40 |
| MiniAmp: power / ground | 5 V, GND | 2, 4 / 6 |
| Encoder A (CLK) | GPIO17 | 11 |
| Encoder B (DT) | GPIO27 | 13 |
| Encoder push switch (SW) | GPIO22 | 15 |
| Encoder ground | GND | 9 or 14 |
| RTC VCC | 3.3 V | 1 |
| RTC SDA / SCL | GPIO2 / GPIO3 | 3 / 5 |
| RTC ground | GND | 9 |

- The Pi's internal pull-ups are enabled on the encoder pins, so a bare
  encoder works. A module with its own pull-ups (KY-040) has a `+` pin: put
  it on **3.3 V (pin 1), never 5 V**.
- Power the RTC from **3.3 V, never 5 V**: its I2C pull-ups go to its supply,
  and the Pi's I2C pins are 3.3 V only. The common ZS-042 DS3231 board has a
  charging circuit meant for a rechargeable LIR2032; with an ordinary CR2032
  remove its resistor (often marked 201) or diode.
- The MiniAmp doesn't use I2C, and none of the knob/RTC pins are its I2S
  pins. Check HiFiBerry's MiniAmp documentation in case your board uses
  GPIO16/26 for mute or shutdown; nothing else here uses them.

### config.txt

```ini
dtparam=audio=off
dtoverlay=hifiberry-dac                 # the MiniAmp
gpio=17,27=ip,pu                        # encoder pull-ups
dtoverlay=rotary-encoder,pin_a=17,pin_b=27,relative_axis=1
dtoverlay=gpio-key,gpio=22,active_low=1,gpio_pull=up,keycode=164,label="PLAYPAUSE"
# dtoverlay=i2c-rtc,ds3231              # once the RTC is fitted
```

The kernel turns the encoder and switch into input events, which the station
reads from `/dev/input` (`sleepradiopi/io/knob.py`): no GPIO library needed,
and any encoder or button the kernel knows works. The user running the
station must be in the `input` and `audio` groups.

## Running it

There are two ways:

- **The appliance image** (for the finished radio): a separate,
  Buildroot-based image that boots from a read-only root, keeps settings on
  a small data partition and the music on a read-only one, starts the
  station at power-up, and updates over Wi-Fi into a spare root slot. It's
  built from a separate repo.
- **Raspberry Pi OS** (development): see [`docs/PI_SETUP.md`](docs/PI_SETUP.md).

```bash
./scripts/deploy.sh                 # on the desktop: sync to the Pi, run the tests there
./scripts/install_service.sh        # on the Pi, once: start the station at boot
```

### Files

| What | Where (defaults; all can be set in the config) |
|---|---|
| Settings | `~/.config/sleepradiopi/config.json` (created on first run) |
| Music | `~/media/music/<Artist>/<Album>/NN - Title.ext` |
| Jingles | `~/media/jingles/` |
| Voice packs | `voices/<name>/` — `model.onnx`, `tokens.txt`, `espeak-ng-data/` (the same files SleepRadio uses; never committed) |
| DJ hooks | bundled: `sleepradiopi/data/dj_hooks_70s.txt` (a copy of SleepRadio's) |
| Caches | `~/.cache/sleepradiopi/` — `tags.json` (track tags, so start-up takes seconds, not a minute), `scans.json` (loudness) |
| Volume | `~/.local/state/sleepradiopi/speaker.json` |

### Settings you're likely to change

| Key | Default | |
|---|---|---|
| `speaker_enabled` | `false` | Play through the sound card from start-up (the appliance turns it on). Off by default so a desktop test run doesn't play out loud. |
| `speaker_device` | `"default"` | ALSA device. |
| `speaker_volume` | `30` | Volume on the very first start; after that the knob's last setting. |
| `knob_step` | `2` | Volume steps per click (1 dB). |
| `broadcast_voice` | `"stock"` | `"stock"` or `"personal"` (a folder in the voices folder). |
| `broadcast_chattiness`, `broadcast_jingle_every`, `broadcast_dj_hooks`, `news_enabled`, `news_quiet_hours`, ... | | See `sleepradiopi/config/settings.py`. |

The "is the clock right?" check reads `SLEEPRADIOPI_CLOCK_FLAG`: a file that
exists once the time is known (the appliance creates `/run/time-synced` when
NTP sets the clock). If the variable isn't set, the clock is trusted.

### Web page and API

- **http://sleepradiopi.local/** — listen in a browser, now playing, history.
- `GET /api/status` — what's on air, the library, the voice, the speaker.
- `POST /api/speaker` with JSON `{"volume": 0-100}`, `{"step": n}` or
  `{"pause": true | false | "toggle"}` — the knob's controls, for testing.

No login: it's meant for a home network. Once the speaker is the main
output, the plan is a small status/settings page and the browser stream off
by default (see the roadmap).

## Why Python

The one piece of SleepRadio that has to carry over byte-for-byte — the
on-device cloned TTS voice via `sherpa-onnx` — has a first-class Python
binding that runs unchanged on Raspberry Pi ARM, and ffmpeg does the audio
work. See `docs/SCOPE.md` for the full stack rationale.

## License

GPL-3.0-or-later — see [`NOTICE`](NOTICE) for why (short version: the offline
TTS engine statically links eSpeak-NG, which is GPL).

## Layout

```
sleepradiopi/
  broadcast/   The station: show clock, DJ scripts, track selection, news, library scan (+ tag cache)
  audio/       PCM via ffmpeg (decode, loudness, voice EQ); speaker.py plays through aplay with volume
  tts/         sherpa-onnx voice, run in a recycled worker process
  web/         MP3 stream + the listen-in page + /api/status, /api/speaker
  config/      Settings (JSON), atomic file writes, "is the clock right?"
  io/          knob.py: the rotary encoder + push switch (Linux input events)
  data/        dj_hooks_70s.txt
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
