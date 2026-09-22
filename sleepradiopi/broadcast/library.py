"""Find the music and jingles on disk.

Plain paths replace SleepRadio's SAF folder pickers. Tags come from
mutagen; a file with no tags falls back to its file name (dropping a
leading "NN - " track number) and its artist folder, matching the
Artist/Album/NN - Title layout of the SleepRadioMusic library.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import mutagen

from .models import BroadcastTrack, JingleClip

log = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav"}
_TRACK_NUMBER = re.compile(r"^\d+\s*[-.]\s*")


def _audio_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS)


def _tags(path: Path):
    try:
        return mutagen.File(path, easy=True)
    except Exception:
        return None


def read_track(path: Path, root: Path) -> BroadcastTrack:
    tags = _tags(path)

    def tag(name: str) -> str:
        return ((tags.get(name) if tags else None) or [""])[0].strip()

    rel = path.relative_to(root)
    folder_artist = rel.parts[0] if len(rel.parts) > 2 else ""
    return BroadcastTrack(
        path=path,
        title=tag("title") or _TRACK_NUMBER.sub("", path.stem).replace("_", " "),
        artist=tag("artist") or tag("albumartist") or folder_artist,
        album=tag("album") or (rel.parts[-2] if len(rel.parts) > 1 else ""),
    )


def scan_music(folder: Path) -> list[BroadcastTrack]:
    tracks = [read_track(p, folder) for p in _audio_files(folder)]
    log.info("music: %d tracks in %s", len(tracks), folder)
    return tracks


def scan_jingles(folder: Path) -> list[JingleClip]:
    clips = []
    for p in _audio_files(folder):
        tags = _tags(p)
        length = getattr(getattr(tags, "info", None), "length", 0) or 0
        clips.append(JingleClip(p, float(length)))
    log.info("jingles: %d in %s", len(clips), folder)
    return clips
