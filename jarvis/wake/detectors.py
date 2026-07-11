"""Production wake-word engines (adapted from benches/wake_word_ab/detectors.py).

Audio never leaves the machine — both engines run fully offline.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from jarvis.wake.base import SAMPLE_RATE, Detection


class OpenWakeWordDetector:
    """openWakeWord pre-trained 'hey jarvis' model (ONNX on Windows)."""

    name = "openWakeWord"
    phrase = "hey jarvis"

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        chunk_samples: int = 1280,
        inference_framework: str = "onnx",
    ) -> None:
        import openwakeword
        from openwakeword.model import Model

        openwakeword.utils.download_models()

        self._threshold = threshold
        self._chunk_samples = chunk_samples

        jarvis_paths = self._find_hey_jarvis_models(inference_framework)
        if jarvis_paths:
            self._model = Model(
                wakeword_models=jarvis_paths,
                inference_framework=inference_framework,
            )
        else:
            self._model = Model(inference_framework=inference_framework)

        self._target_keys = [
            k for k in self._model.models.keys() if "jarvis" in k.lower()
        ]
        if not self._target_keys:
            self._target_keys = list(self._model.models.keys())

    @staticmethod
    def _find_hey_jarvis_models(inference_framework: str) -> list[str]:
        import openwakeword

        root = Path(openwakeword.__file__).resolve().parent
        ext = ".onnx" if inference_framework == "onnx" else ".tflite"
        matches = sorted(root.rglob(f"*hey_jarvis*{ext}"))
        return [str(p) for p in matches]

    @property
    def frame_length(self) -> int:
        return self._chunk_samples

    def process(self, frame_i16: Any) -> Detection | None:
        prediction = self._model.predict(frame_i16)
        best_key = None
        best_score = -1.0
        for key in self._target_keys:
            score = float(prediction.get(key, 0.0))
            if score > best_score:
                best_score = score
                best_key = key
        if best_key is not None and best_score >= self._threshold:
            return Detection(detector=self.name, score=best_score)
        return None

    def reset(self) -> None:
        model = self._model
        if model is None:
            return
        buf = getattr(model, "prediction_buffer", None)
        if isinstance(buf, dict):
            for key in list(buf.keys()):
                try:
                    buf[key].clear()
                except Exception:
                    pass

    def close(self) -> None:
        self._model = None  # type: ignore[assignment]


class PorcupineDetector:
    """Picovoice Porcupine with built-in 'jarvis' keyword.

    Requires env PICOVOICE_ACCESS_KEY (free key from https://console.picovoice.ai/).
    """

    name = "Porcupine"
    phrase = "jarvis"

    def __init__(
        self,
        *,
        access_key: str | None = None,
        sensitivity: float = 0.5,
        keyword: str = "jarvis",
    ) -> None:
        import pvporcupine

        key = access_key or os.environ.get("PICOVOICE_ACCESS_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "Porcupine requires PICOVOICE_ACCESS_KEY "
                "(free at https://console.picovoice.ai/)."
            )
        if keyword not in pvporcupine.KEYWORDS:
            raise RuntimeError(
                f"Keyword {keyword!r} not in Porcupine builtins: "
                f"{sorted(pvporcupine.KEYWORDS)}"
            )
        self._porcupine = pvporcupine.create(
            access_key=key,
            keywords=[keyword],
            sensitivities=[sensitivity],
        )
        if int(self._porcupine.sample_rate) != SAMPLE_RATE:
            rate = self._porcupine.sample_rate
            self._porcupine.delete()
            raise RuntimeError(
                f"Porcupine sample_rate={rate} != expected {SAMPLE_RATE}"
            )
        self._keyword = keyword

    @property
    def frame_length(self) -> int:
        return int(self._porcupine.frame_length)

    @property
    def sample_rate(self) -> int:
        return int(self._porcupine.sample_rate)

    def reset(self) -> None:
        return

    def process(self, frame_i16: Any) -> Detection | None:
        index = self._porcupine.process(frame_i16)
        if index >= 0:
            return Detection(
                detector=self.name,
                score=None,
                keyword_index=int(index),
            )
        return None

    def close(self) -> None:
        try:
            self._porcupine.delete()
        except Exception:
            pass
