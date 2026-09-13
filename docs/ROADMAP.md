# Roadmap

Rough build order — each milestone should be independently testable on real
hardware before moving to the next. Nothing here is scheduled; it's a
sequence, not a timeline.

1. **Audio-out smoke test** — confirm the HiFiBerry board shows up as an ALSA
   device and plays a test tone / a single file via the chosen playback
   library (`python-vlc` or `mpv`).
2. **Local music playback** — scan a folder, build an "album" list (mirrors
   SleepRadio's "any subfolder with audio files is an album" rule), play
   sequentially, read tags via `mutagen`.
3. **Audiobooks** — same folder scan, but per-book resume position persisted
   to the settings store.
4. **Internet radio** — stream an HTTP/HLS URL, surface ICY now-playing
   metadata if present.
5. **Ambient mixer** — port `NoiseGenerator`/`BinauralGenerator`'s waveform
   math to `numpy`, output via a second `sounddevice` stream mixed under
   Channel A.
6. **Sleep timer** — fade-and-stop Channel A on schedule; ambient channels
   keep running.
7. **TTS pipeline reuse** — load an imported voice pack via `sherpa-onnx`'s
   Python binding, synthesise a test line, play it back. This should be a
   near-direct reuse of the existing voice files, so it's a good early
   milestone to de-risk.
8. **Broadcast auto-DJ** — port `BroadcastSelector`/`DjScriptBuilder`'s logic
   to Python: track selection, spoken links between tracks, jingle
   scheduling.
9. **Buttons + LCD** — wire physical input (`gpiozero`) and status display
   (`luma.lcd`/`RPLCD`) to the state machine built in steps 1-8.
10. **Integration pass** — settings persistence, config file for folder
    paths / pin mapping / display type, error handling for missing
    hardware/streams.

Podcasts and any future networked-control feature are explicitly deferred
past v1 — see `docs/SCOPE.md`.
