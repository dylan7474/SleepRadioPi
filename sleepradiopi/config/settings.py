"""Flat-file settings store (JSON on disk).

Covers what SleepRadio's SettingsRepository persists via DataStore, adapted
for plain filesystem paths instead of SAF tree URIs:

    music_folder, audiobooks_folder, jingles_folder   (plain paths)
    presets[1..4]                                     (source assignments)
    broadcast_voice, broadcast_chattiness
    broadcast_jingle_enabled, broadcast_jingle_every
    broadcast_announcer_volume, broadcast_announcer_speed
    custom_stations
    gpio_pin_mapping, lcd_panel_type                  (Pi-specific, new)
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Settings:
    music_folder: str | None = None
    audiobooks_folder: str | None = None
    jingles_folder: str | None = None
    presets: dict = field(default_factory=dict)
    custom_stations: list = field(default_factory=list)
    broadcast_voice: str | None = None
    broadcast_chattiness: str = "balanced"
    broadcast_jingle_enabled: bool = False
    broadcast_jingle_every: int = 4
    broadcast_announcer_volume: float = 1.0
    broadcast_announcer_speed: float = 1.0
    gpio_pin_mapping: dict = field(default_factory=dict)
    lcd_panel_type: str | None = None


def load(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    return Settings(**json.loads(path.read_text()))


def save(path: Path, settings: Settings) -> None:
    path.write_text(json.dumps(asdict(settings), indent=2))
