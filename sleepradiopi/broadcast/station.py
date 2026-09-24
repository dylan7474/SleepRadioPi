"""The Broadcast Radio station: one continuous show, rendered in real time.

A port of the Broadcast half of SleepRadio's PlaybackConnection.kt. The
show runs on one producer thread that writes 16-bit stereo PCM to an
Output (the MP3 web stream today; the HiFiBerry via ALSA later), and the
Output paces it to real time.

What happens in the gap after each track is planned when the track starts
(ShowClock decides link / ident / time check; jingles every N tracks), and
its speech is synthesised then, while the track plays -- the personal voice
is slower than realtime on a Pi Zero, so nothing is made on demand if it
can be helped. The two things that depend on *when* they're heard are made
just in time instead:

  * the time check is worded PREFETCH_S before the track ends, from the
    real end time (the stream is realtime with no skip or pause, so that
    projection is exact -- the fix the Android app needed JIT wording for);
  * a news bulletin is fetched and synthesised up to 15 minutes ahead, but
    only read if its :00/:30 window is open when the gap actually comes,
    with its time line ("It's just gone ten o'clock") worded at prefetch.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import numpy as np

from sleepradiopi.audio import pcm
from sleepradiopi.config.clock import clock_trusted
from sleepradiopi.tts.worker import TtsWorker

from .library import scan_jingles, scan_music
from .models import BroadcastConfig, BroadcastTrack, Chattiness, JingleClip, LinkKind
from .news import DueNews, NewsRepository, NewsSchedule, QuietHours, build_bulletin_body, bulletin_time_line
from .script_builder import DjScriptBuilder, ShowClock
from .selector import BroadcastSelector, HookPool, parse_hooks

log = logging.getLogger(__name__)

LOOKAHEAD = 3             # tracks picked (and loudness-scanned) ahead
PREFETCH_S = 45.0         # word the time check / news time line this long before a track ends
                          # (room for a TTS worker recycle, ~15 s, to finish first)
STARTUP_JINGLE_MAX_S = 45.0
SPEECH_PAD_S = 0.25       # breath of silence either side of the DJ
SPEECH_WAIT_S = 45.0      # give up on a line that still isn't synthesised after this
PER_LINE_ESTIMATE_S = 4.0  # rough length of a spoken line, for wording a clock after one


class Output(Protocol):
    def start(self) -> None: ...
    def write(self, block: np.ndarray) -> None: ...
    def stop(self) -> None: ...


@dataclass
class Speech:
    text: str
    voice: str
    future: Future


@dataclass
class ClockStep:
    speech: Speech | None = None


@dataclass
class NewsItem:
    due: DueNews
    headlines: list[str]
    body: Speech
    time_line: Speech | None = None


@dataclass
class Step:
    kind: str  # "say" | "clock" | "jingle" | "news"
    speech: Speech | None = None
    clock: ClockStep | None = None
    jingle: JingleClip | None = None
    news: NewsItem | None = None

    def describe(self) -> str:
        if self.kind == "say":
            return f'say("{self.speech.text}")'
        return self.kind


@dataclass
class OnAir:
    kind: str       # "track" | "dj" | "jingle" | "news"
    title: str
    artist: str = ""
    album: str = ""
    started: float = field(default_factory=time.time)
    duration_s: float = 0.0


class Station:
    def __init__(self, cfg: dict, tts: TtsWorker | None, output: Output) -> None:
        self.music_dir: Path = cfg["music_folder"]
        self.jingles_dir: Path = cfg["jingles_folder"]
        self.dj_voice: str | None = cfg["broadcast_voice"]
        news_voice = cfg["news_voice"]
        self.news_voice: str = self.dj_voice if news_voice in (None, "same") else news_voice
        self.announcer_volume: float = cfg["broadcast_announcer_volume"]
        self.grace_s: float = cfg["listener_grace_s"]
        chattiness = Chattiness.from_id(cfg["broadcast_chattiness"])
        self.config = BroadcastConfig(
            tracks_per_link=chattiness.tracks_per_link,
            announce_every_track=chattiness == Chattiness.MAXIMUM,
            announcer_speed=cfg["broadcast_announcer_speed"],
            news_speed=cfg["news_speed"],
            jingle_every=cfg["broadcast_jingle_every"] if cfg["broadcast_jingle_enabled"] else 0,
            dj_hooks_enabled=cfg["broadcast_dj_hooks"],
            news_enabled=cfg["news_enabled"],
            news_quiet_hours=cfg["news_quiet_hours"],
            news_quiet_start_min=cfg["news_quiet_start_min"],
            news_quiet_end_min=cfg["news_quiet_end_min"],
        )
        self.tts = tts
        self.output = output
        self.scans = pcm.ScanCache(cfg["scan_cache"])

        hooks = None
        if self.config.dj_hooks_enabled and cfg["hooks_file"] and Path(cfg["hooks_file"]).is_file():
            hooks = HookPool(parse_hooks(Path(cfg["hooks_file"]).read_text()))
        self.builder = DjScriptBuilder(hooks=hooks)
        self.news_schedule = NewsSchedule(
            QuietHours.of_minutes(self.config.news_quiet_start_min, self.config.news_quiet_end_min)
            if self.config.news_quiet_hours else None)
        self.news_repo = NewsRepository()

        self.tracks = scan_music(self.music_dir, cfg.get("tag_cache"))
        self.selector = BroadcastSelector(self.tracks)
        self.jingles = scan_jingles(self.jingles_dir) if self.config.jingle_every else []
        self._jingle_paths = {j.path for j in self.jingles}
        self._jingle_bag: deque[JingleClip] = deque()
        self._last_jingle: JingleClip | None = None

        self._tts_pool = ThreadPoolExecutor(1, thread_name_prefix="speech")
        self._scan_pool = ThreadPoolExecutor(1, thread_name_prefix="scan")
        self._scan_futures: dict[Path, Future] = {}
        for j in self.jingles:  # a handful of short files: scan them all once, up front
            self._scan(j.path)

        self._lock = threading.Lock()
        self._listeners = 0
        self._stop_timer: threading.Timer | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue: deque[BroadcastTrack] = deque()
        self._show_clock = ShowClock(self.config)
        self._tracks_since_jingle = 0
        self._news_prep_key: str | None = None
        self._news_ready: NewsItem | None = None
        self._opening: tuple[str, list[Step], BroadcastTrack] | None = None
        self._plan: list[Step] = []

        self.on_air: OnAir | None = None
        self.next_track: BroadcastTrack | None = None
        self.gap_plan: list[str] = []
        self.history: deque[dict] = deque(maxlen=12)
        self.shows_started = 0
        self._prepare_opening()

    # --- listeners / show lifecycle ---------------------------------------------------

    def listener_joined(self) -> None:
        with self._lock:
            self._listeners += 1
            if self._stop_timer:
                self._stop_timer.cancel()
                self._stop_timer = None
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._run_show, name="show", daemon=True)
                self._thread.start()

    def listener_left(self) -> None:
        with self._lock:
            self._listeners = max(0, self._listeners - 1)
            if self._listeners == 0 and self._stop_timer is None:
                self._stop_timer = threading.Timer(self.grace_s, self._end_show)
                self._stop_timer.daemon = True
                self._stop_timer.start()

    def _end_show(self) -> None:
        with self._lock:
            self._stop_timer = None
            if self._listeners == 0:
                log.info("no listeners for %.0fs: ending the show", self.grace_s)
                self._stop.set()

    @property
    def is_on_air(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_show(self) -> None:
        self.shows_started += 1
        self._show_clock.reset()
        self._tracks_since_jingle = 0
        self.output.start()
        try:
            if not self.tracks:
                log.error("no music in %s: nothing to broadcast", self.music_dir)
                while not self._stop.is_set():
                    self._write(pcm.silence(0.5))
                return
            steps, first = self._take_opening()
            self._run_steps(steps)
            track = first
            while not self._stop.is_set():
                self._play_track(track)
                if self._stop.is_set():
                    break
                self._run_gap()
                track = self._take_next()
        except Exception:
            log.exception("show crashed")
        finally:
            self.output.stop()
            self.on_air = None
            self.gap_plan = []
            log.info("show ended")
            self._prepare_opening()

    # --- output -----------------------------------------------------------------------

    def _write(self, block: np.ndarray) -> None:
        self.output.write(block)

    def _await(self, fut: Future, limit_s: float = SPEECH_WAIT_S):
        """Wait for background work while keeping the stream fed with silence, so a slow
        synthesis is a pause on air rather than a dropped connection."""
        deadline = time.monotonic() + limit_s
        while not fut.done():
            if self._stop.is_set() or time.monotonic() > deadline:
                return None
            self._write(pcm.silence(0.1))
        try:
            return fut.result()
        except Exception as e:
            log.warning("background job failed: %s", e)
            return None

    # --- speech ----------------------------------------------------------------------

    def _say(self, text: str, voice: str | None = None, speed: float | None = None) -> Speech:
        voice = voice or self.dj_voice
        speed = speed or self.config.announcer_speed

        def job() -> np.ndarray:
            t0 = time.monotonic()
            samples, rate = self.tts.synth(voice, text, speed)
            out = pcm.speech_pcm(samples, rate, self.announcer_volume)
            log.info("synth %s %.1fs of speech in %.1fs: %s", voice, len(out) / pcm.SAMPLE_RATE,
                     time.monotonic() - t0, text[:70])
            return out

        return Speech(text, voice, self._tts_pool.submit(job))

    @property
    def _has_voice(self) -> bool:
        return self.tts is not None and self.dj_voice is not None

    def _speak(self, speech: Speech, kind: str = "dj") -> None:
        audio = self._await(speech.future)
        if audio is None:
            log.warning("dropped line (not ready): %s", speech.text)
            return
        self.on_air = OnAir(kind, speech.text, duration_s=len(audio) / pcm.SAMPLE_RATE)
        self.history.appendleft({"kind": kind, "text": speech.text, "at": time.time()})
        self._write(pcm.silence(SPEECH_PAD_S))
        for block in pcm.blocks(audio):
            if self._stop.is_set():
                return
            self._write(block)
        self._write(pcm.silence(SPEECH_PAD_S))

    # --- tracks ----------------------------------------------------------------------

    def _scan(self, path: Path) -> Future:
        fut = self._scan_futures.get(path)
        if fut is None:
            fut = self._scan_futures[path] = self._scan_pool.submit(self.scans.scan, path)
        return fut

    def _refill(self) -> None:
        while len(self._queue) < LOOKAHEAD:
            t = self.selector.next_track()
            if t is None:
                return
            self._queue.append(t)
            self._scan(t.path)

    def _take_next(self) -> BroadcastTrack:
        self._refill()
        t = self._queue.popleft()
        self._refill()
        return t

    def _play_file(self, path: Path, on_air: OnAir, near_end=None) -> None:
        scan = self._await(self._scan(path), 60) or pcm.NO_SCAN
        if path not in self._jingle_paths:  # jingles recur; tracks' futures can go
            self._scan_futures.pop(path, None)
        playable_s = scan.playable_ms / 1000
        on_air.duration_s = playable_s
        on_air.started = time.time()
        self.on_air = on_air
        played = 0
        fired = near_end is None
        for block in pcm.decode(path, scan.start_ms, scan.end_ms):
            if self._stop.is_set():
                return
            self._write(pcm.apply_gain(block, scan.gain))
            played += len(block)
            if not fired and playable_s and playable_s - played / pcm.SAMPLE_RATE <= PREFETCH_S:
                fired = True
                near_end(datetime.now() + timedelta(seconds=playable_s - played / pcm.SAMPLE_RATE))
        if not fired:
            near_end(datetime.now())

    def _play_track(self, track: BroadcastTrack) -> None:
        self._refill()
        self.next_track = self._queue[0] if self._queue else None
        plan = self._plan_gap(track, self.next_track)
        self._plan = plan
        self.gap_plan = [s.describe() for s in plan]
        self._maybe_prepare_news()
        log.info("now: %s by %s | after it: %s", track.title, track.artist, self.gap_plan or "straight on")
        self.history.appendleft({"kind": "track", "text": f"{track.title} — {track.artist}", "at": time.time()})
        self._play_file(track.path, OnAir("track", track.title, track.artist, track.album),
                        near_end=lambda end_at: self._prefetch_gap(plan, end_at))

    # --- the gap between tracks ---------------------------------------------------------

    def _jingle_due(self) -> bool:
        if self.config.jingle_every <= 0 or not self.jingles:
            return False
        self._tracks_since_jingle += 1
        if self._tracks_since_jingle < self.config.jingle_every:
            return False
        self._tracks_since_jingle = 0
        return True

    def _next_jingle(self) -> JingleClip | None:
        if not self.jingles:
            return None
        if not self._jingle_bag:
            bag = self.jingles[:]
            random.shuffle(bag)
            if len(bag) > 1 and bag[0] == self._last_jingle:
                bag.append(bag.pop(0))
            self._jingle_bag.extend(bag)
        self._last_jingle = self._jingle_bag.popleft()
        return self._last_jingle

    def _plan_gap(self, prev: BroadcastTrack, nxt: BroadcastTrack | None) -> list[Step]:
        """onBroadcastTrackStarted: what fills the gap after [prev]."""
        kind = self._show_clock.on_track_started(datetime.now().time())
        if kind == LinkKind.TIME_CHECK and not clock_trusted():
            kind = LinkKind.LINK   # offline, the clock may be hours out: say no times
        jingle_due = self._jingle_due()
        b, voice = self.builder, self._has_voice
        steps: list[Step] = []
        talky = kind in (LinkKind.LINK, LinkKind.TIME_CHECK)
        if jingle_due and voice and talky:
            steps.append(Step("say", self._say(b.outro_line(prev))))
            if kind == LinkKind.TIME_CHECK:
                steps.append(Step("clock", clock=ClockStep()))
            steps.append(Step("jingle"))
            steps.append(Step("say", self._say(b.intro_line(nxt))))
        elif jingle_due:
            steps.append(Step("jingle"))
        elif voice and kind == LinkKind.TIME_CHECK:
            if self.config.announce_every_track:
                steps.append(Step("say", self._say(b.outro_line(prev))))
            steps.append(Step("clock", clock=ClockStep()))
            if nxt is not None:
                steps.append(Step("say", self._say(b.intro_line(nxt))))
        elif voice and kind != LinkKind.NONE:
            text = b.build(kind, prev, nxt, announce_every_track=self.config.announce_every_track)
            if text:
                steps.append(Step("say", self._say(text)))
        return steps

    def _prefetch_gap(self, plan: list[Step], end_at: datetime) -> None:
        """PREFETCH_S before the track ends: word anything time-dependent from the real
        end time, so it's synthesised by the time the gap arrives."""
        news = self._news_ready
        if news and news.time_line is None:
            due = self.news_schedule.due_at(end_at)
            if due and due.key == news.due.key:
                news.time_line = self._say(bulletin_time_line(news.due.mark, end_at),
                                           self.news_voice, self.config.news_speed)
        offset = 0.0
        for step in plan:
            if step.kind == "say":
                offset += PER_LINE_ESTIMATE_S
            elif step.kind == "clock" and step.clock.speech is None:
                step.clock.speech = self._say(self.builder.time_line((end_at + timedelta(seconds=offset)).time()))
            elif step.kind == "jingle":
                break

    def _run_gap(self) -> None:
        plan = self._plan
        news = self._news_ready
        if news is not None and self.config.news_enabled:
            due = self.news_schedule.due_at(datetime.now())
            if due is not None and due.key == news.due.key:
                self.news_schedule.mark_read(due)
                self._news_ready = None
                had_jingle = any(s.kind == "jingle" for s in plan)
                plan = [Step("news", news=news)]
                if had_jingle:
                    plan.append(Step("jingle"))
                if self._has_voice:
                    plan.append(Step("say", self._say(self.builder.intro_line(self.next_track))))
                log.info("gap (news): %s", [s.describe() for s in plan])
        self._run_steps(plan)

    def _run_steps(self, steps: list[Step]) -> None:
        for step in steps:
            if self._stop.is_set():
                return
            if step.kind == "say":
                self._speak(step.speech)
            elif step.kind == "clock":
                if step.clock.speech is None:  # no prefetch (unknown track length): word it now
                    step.clock.speech = self._say(self.builder.time_line())
                self._speak(step.clock.speech)
            elif step.kind == "jingle":
                clip = step.jingle or self._next_jingle()
                if clip is not None:
                    name = clip.path.stem.replace("_", " ")
                    self.history.appendleft({"kind": "jingle", "text": name, "at": time.time()})
                    self._play_file(clip.path, OnAir("jingle", name))
            elif step.kind == "news":
                self._read_news(step.news)

    # --- news --------------------------------------------------------------------------

    def _maybe_prepare_news(self) -> None:
        # News is scheduled by the clock (and needs the internet anyway).
        if not (self.config.news_enabled and self.tts is not None and clock_trusted()):
            return
        due = self.news_schedule.prep_at(datetime.now())
        if due is None or due.key == self._news_prep_key:
            return
        self._news_prep_key = due.key
        self._news_ready = None

        def prepare() -> None:
            headlines = self.news_repo.headlines_for(due.slot)
            body = build_bulletin_body(due.slot, headlines)
            if body is None:
                log.info("news %s: no stories (offline or nothing new)", due.slot.value)
                self._news_prep_key = None  # retry at the next track start
                return
            speech = self._say(body, self.news_voice, self.config.news_speed)
            self._news_ready = NewsItem(due, headlines, speech)
            log.info("news %s for %s prepared: %d stories", due.slot.value, due.mark.strftime("%H:%M"),
                     len(headlines))

        threading.Thread(target=prepare, name="news-prep", daemon=True).start()

    def _read_news(self, news: NewsItem) -> None:
        if news.time_line is None:
            news.time_line = self._say(bulletin_time_line(news.due.mark, datetime.now()),
                                       self.news_voice, self.config.news_speed)
        self._speak(news.time_line, "news")
        self._speak(news.body, "news")
        self.news_repo.mark_read(news.headlines)

    # --- opening ----------------------------------------------------------------------

    def _prepare_opening(self) -> None:
        """Pick the first track and synthesise the welcome while idle, so tuning in
        starts at once. Rebuilt if the greeting's time of day has changed."""
        if not self.tracks:
            return
        first = self._take_next()
        greeting = self.builder.welcome_greeting(time_known=clock_trusted())
        steps: list[Step] = []
        startup = [j for j in self.jingles if 0 < j.duration_s < STARTUP_JINGLE_MAX_S]
        if self._has_voice:
            if startup:
                steps = [Step("say", self._say(greeting)),
                         Step("jingle", jingle=random.choice(startup)),
                         Step("say", self._say(self.builder.welcome_first_track(first)))]
            else:
                steps = [Step("say", self._say(f"{greeting} {self.builder.welcome_first_track(first)}"))]
        elif startup:
            steps = [Step("jingle", jingle=random.choice(startup))]
        self._opening = (greeting, steps, first)

    def _take_opening(self) -> tuple[list[Step], BroadcastTrack]:
        opening = self._opening
        if opening is None or opening[0] != self.builder.welcome_greeting():
            if opening is not None:
                self._queue.appendleft(opening[2])
            self._prepare_opening()
            opening = self._opening
        self._opening = None
        return opening[1], opening[2]

    # --- status ----------------------------------------------------------------------

    def status(self) -> dict:
        on_air = self.on_air
        nxt = self.next_track
        news = self._news_ready
        return {
            "on_air": self.is_on_air,
            "listeners": self._listeners,
            "now": None if on_air is None else {
                "kind": on_air.kind, "title": on_air.title, "artist": on_air.artist,
                "album": on_air.album, "elapsed_s": round(time.time() - on_air.started, 1),
                "duration_s": round(on_air.duration_s, 1),
            },
            "next": None if nxt is None else {"title": nxt.title, "artist": nxt.artist},
            "gap_plan": self.gap_plan,
            "news_ready": None if news is None else news.due.mark.strftime("%H:%M"),
            "history": list(self.history),
            "library": {"tracks": len(self.tracks), "jingles": len(self.jingles)},
            "voices_ready": bool(self.tts and self.tts.ready),
            "voice": {"name": self.dj_voice, "rss_mb": self.tts.last_rss_mb, "restarts": self.tts.restarts}
            if self.tts else None,
        }
