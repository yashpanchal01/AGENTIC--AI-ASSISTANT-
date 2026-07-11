"""Wake-word detector protocol — fully local, frame-based."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# Detectors (Porcupine / openWakeWord) expect 16 kHz mono int16 PCM.
SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class Detection:
    """One positive wake-word hit from a local detector."""

    detector: str
    score: float | None = None
    keyword_index: int | None = None


@runtime_checkable
class WakeDetector(Protocol):
    """Uniform process(frame) surface for production + fakes + benches."""

    name: str
    phrase: str

    @property
    def frame_length(self) -> int:
        """Samples required per process() call."""
        ...

    def process(self, frame_i16: Any) -> Detection | None:
        """Run one frame. frame_i16 is a 1-D numpy int16 array of frame_length."""
        ...

    def close(self) -> None:
        ...
