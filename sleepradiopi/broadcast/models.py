"""Broadcast state/config data classes.

Port of SleepRadio's BroadcastModels.kt: track/jingle references, the
chattiness setting (how often a spoken link happens), and the segue-step
sequencing (say / play jingle / play track) used to build one on-air
transition.
"""

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path


@dataclass
class BroadcastTrack:
    path: Path
    title: str
    artist: str


@dataclass
class JingleClip:
    path: Path
    duration_ms: int


class Chattiness(Enum):
    MAXIMUM = auto()
    CHATTY = auto()
    BALANCED = auto()
    MINIMAL = auto()

    @property
    def tracks_per_link(self) -> int:
        """TODO: port the exact mapping from Chattiness.kt."""
        raise NotImplementedError


@dataclass
class BroadcastConfig:
    tracks_per_link: int
    announce_every_track: bool
    announcer_volume: float
    announcer_speed: float
    jingle_every: int
