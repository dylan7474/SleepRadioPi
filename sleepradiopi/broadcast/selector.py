"""Track selection for Broadcast Radio: recency- and artist-spaced shuffle
over the local music pool.

Port of SleepRadio's BroadcastSelector.kt -- pure selection logic, no
Android dependency in the original, so this should be a close translation
rather than a redesign.
"""

from .models import BroadcastTrack


class BroadcastSelector:
    def __init__(self, pool: list[BroadcastTrack]) -> None:
        self.pool = pool

    def next_track(self) -> BroadcastTrack:
        """TODO: port the recency/artist-spacing heuristic from
        BroadcastSelector.kt.
        """
        raise NotImplementedError
