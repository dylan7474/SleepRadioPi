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

## Next

5. **Speakers** — solder the header, fit the MiniAmp, add an ALSA output
   next to the MP3 one (the station writes to an `Output`, so it's the
   same show either way; decide whether the Pi plays locally, streams, or
   both).
6. **Buttons + display** — a small I2C display (OLED preferred for a dark
   bedroom) and a few buttons / a rotary encoder for volume.
7. **Settings from the page** — voice, chattiness, jingles, news, without
   editing JSON.
8. **Library tools** — copying/syncing music from the desktop library.
