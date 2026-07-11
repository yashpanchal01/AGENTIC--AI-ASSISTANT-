"""In-process fake STT for wiring tests (no model, no GPU)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np


class FakeTranscriber:
    """Returns a canned transcript (or a sequence / callable) for any audio."""

    def __init__(
        self,
        text: str | Sequence[str] | Callable[[], str] = "open notepad",
    ) -> None:
        self._seq: list[str] | None
        self._callable: Callable[[], str] | None
        if callable(text) and not isinstance(text, str):
            self._callable = text  # type: ignore[assignment]
            self._seq = None
            self.text = ""
        elif isinstance(text, (list, tuple)):
            self._seq = list(text)
            self._callable = None
            self.text = self._seq[0] if self._seq else ""
        else:
            self._seq = None
            self._callable = None
            self.text = str(text)
        self.calls: list[tuple[int, int]] = []  # (n_samples, sample_rate)
        self.unload_calls: int = 0
        self.loaded: bool = True

    def transcribe(self, audio: np.ndarray, *, sample_rate: int = 16_000) -> str:
        n = int(np.asarray(audio).size)
        self.calls.append((n, sample_rate))
        self.loaded = True
        if self._callable is not None:
            return self._callable()
        if self._seq is not None:
            if not self._seq:
                return ""
            return self._seq.pop(0)
        return self.text

    def unload(self) -> None:
        """Release model resources (mirrors WhisperTranscriber.unload)."""
        self.unload_calls += 1
        self.loaded = False
