"""faster-whisper STT on local GPU (or CPU fallback)."""

from __future__ import annotations

import gc
from pathlib import Path

import numpy as np

from jarvis.stt.dictionary import fix_terms, hotwords_string


class WhisperTranscriber:
    """Local faster-whisper. Raw text + dictionary bias; no polish model.

    Call :meth:`unload` between commands to free VRAM for games / other GPU
    apps (issue #9 coexistence fallback). The next :meth:`transcribe` reloads.
    """

    def __init__(
        self,
        *,
        model_name: str = "distil-whisper/distil-large-v3.5-ct2",
        device: str = "cuda",
        compute_type: str = "int8_float16",
        dictionary_path: Path | None = None,
        apply_term_fixes: bool = True,
    ) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError(
                "faster-whisper is required for STT. "
                'Install with: py -3.13 -m pip install -e ".[voice]"'
            ) from e

        self.model_name = model_name
        self.dictionary_path = dictionary_path
        self.apply_term_fixes = apply_term_fixes
        self._model = None
        self._WhisperModel = WhisperModel
        self._device = device
        self._compute_type = compute_type
        self._using_cpu_fallback = False

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        try:
            self._model = self._WhisperModel(
                self.model_name,
                device=self._device,
                compute_type=self._compute_type,
            )
            self._using_cpu_fallback = False
        except Exception:
            # CPU fallback keeps the loop usable if VRAM is busy.
            self._model = self._WhisperModel(
                "small.en",
                device="cpu",
                compute_type="int8",
            )
            self._using_cpu_fallback = True
        return self._model

    def unload(self) -> None:
        """Drop the model and free GPU memory if possible.

        Safe when already unloaded. Next transcribe() reloads lazily.
        """
        if self._model is None:
            return
        self._model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 — torch optional / best-effort
            pass

    def transcribe(self, audio: np.ndarray, *, sample_rate: int = 16_000) -> str:
        flat = np.asarray(audio, dtype=np.float32).reshape(-1)
        if flat.size < sample_rate // 4:
            return ""

        # faster-whisper expects float32 mono at its native rate; resample if needed.
        if sample_rate != 16_000:
            duration = flat.size / float(sample_rate)
            target_n = max(1, int(duration * 16_000))
            x_old = np.linspace(0.0, 1.0, num=flat.size, endpoint=False)
            x_new = np.linspace(0.0, 1.0, num=target_n, endpoint=False)
            flat = np.interp(x_new, x_old, flat).astype(np.float32)

        hot = hotwords_string(self.dictionary_path)
        model = self._ensure_model()
        segments, _info = model.transcribe(
            flat,
            beam_size=5,
            vad_filter=True,
            language="en",
            hotwords=hot or None,
            initial_prompt=hot or None,
        )
        raw = " ".join(s.text.strip() for s in segments).strip()
        if self.apply_term_fixes and raw:
            raw = fix_terms(raw)
        return raw
