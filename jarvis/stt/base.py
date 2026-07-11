"""Transcriber protocol — audio in, raw transcript text out."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class Transcriber(Protocol):
    """Local speech-to-text. No polish / LLM rewrite — raw (or lightly fixed) text."""

    def transcribe(self, audio: np.ndarray, *, sample_rate: int = 16_000) -> str:
        """Return transcript text for mono float32 audio."""
        ...


@runtime_checkable
class UnloadableTranscriber(Protocol):
    """Optional VRAM coexistence: free the model between commands."""

    def unload(self) -> None:
        """Release GPU/CPU model weights if loaded. Safe to call when idle."""
        ...
