# Roadmap

**Direction (2026-09-22): Broadcast Radio is the product.** The other
SleepRadio sources (local albums, audiobooks, internet radio, ambient noise
and binaural beats) are deferred and may never be built; their placeholder
modules stay in the tree until that's decided.

## Done

1. **Audio-out smoke test script** — `scripts/smoke_test_audio.py` (tone to
   the HiFiBerry). The MiniAmp's overlay is set up and it shows as card 0;
   the tone through real speakers waits on the header being soldered.
2. **Voice (TTS)** — the Android app's voice packs load unchanged via
   sherpa-onnx; `tts/worker.py` runs one voice in a recycled subprocess.
3. **Broadcast station** — ported from SleepRadio: show clock (links,
   idents, time checks), DJ scripts and 70s hooks, track selection, jingles
   (a short one opens the show; one every N tracks), loudness levelling,
   edge-silence trim, voice EQ, news bulletins (BBC RSS, :00 top stories,
   :30 softer stories, quiet hours). Time checks and bulletin time lines
   are worded just before they're spoken, from the real clock.
4. **Listen in a browser** — MP3 stream + page (tune in, volume, sleep
   timer, now playing, recent history) on port 80; systemd service.
5. **Speaker output** — `audio/speaker.py`: the show plays through aplay
   (the MiniAmp) from start-up, alongside the MP3 stream; software volume
   (the MiniAmp has none), remembered across restarts.
6. **The knob** — a rotary encoder for volume, its push switch for pause
   (`io/knob.py`, kernel input events). The only physical control: the
   display and extra buttons are dropped.
7. **Offline mode** — no time checks, time-of-day greetings or news until
   the clock has been set from the internet since power-up.
8. **Faster start** — track tags are cached; the station answers seconds
   after start-up instead of a minute.
9. **Appliance image** — a separate Buildroot image: read-only root, data
   and music partitions, pull-the-plug tested, A/B updates over Wi-Fi.

## Next

10. **Fit the hardware** — solder the header, fit the MiniAmp and the knob,
    first sound; check for underruns and tune the knob's step/direction.
11. **Real-time clock** — a DS3231 so the time is known offline: time checks
    and news without a network.
12. **A smaller web side** — once the speaker is the main output: the browser
    stream off by default (it runs an MP3 encoder all the time), and one
    status/settings page (now playing, volume, voice, chattiness, news,
    recent log lines) instead of editing JSON. No updates from the page.
13. **Library tools** — copying/syncing music from the desktop library.
