"""DJ script text generation: welcome greeting, first-track intro, and
between-track links that name what just played and what's next.

Port of SleepRadio's DjScriptBuilder.kt -- pure text templating with a
random-choice element (e.g. WELCOME_TAILS), no Android dependency.
"""

from datetime import time as time_of_day

from .models import BroadcastTrack


class DjScriptBuilder:
    def welcome_greeting(self, now: time_of_day | None = None) -> str:
        """TODO: port the time-of-day greeting logic ("Good evening, ...")."""
        raise NotImplementedError

    def welcome_first_track(self, first: BroadcastTrack) -> str:
        raise NotImplementedError

    def link(self, just_played: BroadcastTrack, next_track: BroadcastTrack) -> str:
        """The between-track spoken link, e.g.
        'We just heard <title>, by <artist>. Let's hear <title>, by <artist>.'
        """
        raise NotImplementedError
