"""Loads a voice pack and synthesises speech via sherpa-onnx.

Voice pack layout matches SleepRadio's VoicePack.kt exactly, so a pack
exported from the Android app (or built by its tools/build-stock-voice.sh)
can be copied into voices/<id>/ here unmodified:

    voices/<id>/model.onnx
    voices/<id>/model.onnx.json   (optional -- sample rate)
    voices/<id>/tokens.txt
    voices/<id>/espeak-ng-data/   (optional -- a model-only pack can borrow
                                    another installed pack's copy)
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TtsAudio:
    samples: "list[float]"  # mono float PCM in [-1, 1]
    sample_rate: int


class OfflineTtsEngine:
    """Thin wrapper around sherpa_onnx.OfflineTts for one loaded voice pack.

    Mirrors SleepRadio's OfflineTtsEngine.kt: load() and synth() are
    synchronous/blocking, call off the main thread/loop.
    """

    def __init__(self) -> None:
        self._loaded_id: str | None = None

    def ensure_loaded(self, voice_dir: Path, voice_id: str) -> bool:
        """TODO: build sherpa_onnx.OfflineTtsConfig from voice_dir and
        construct sherpa_onnx.OfflineTts, matching OfflineTtsEngine.kt's
        config shape.
        """
        raise NotImplementedError

    def synth(self, text: str, speed: float = 1.0) -> TtsAudio:
        raise NotImplementedError
