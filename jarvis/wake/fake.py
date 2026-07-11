"""Injectable wake detector for automated tests (no mic, no model)."""

from __future__ import annotations

from collections import deque
from typing import Any, Iterable

import numpy as np

from jarvis.wake.base import Detection


class FakeWakeDetector:
    """Scripted detector: process() returns queued detections then None.

    Use ``fire()`` to enqueue a hit from another thread (hotkey-style tests),
    or pass ``detections`` at construction for frame-driven scripts.
    """

    name = "fake"
    phrase = "jarvis"

    def __init__(
        self,
        *,
        detections: Iterable[bool | Detection | None] | None = None,
        frame_length: int = 512,
        # Fire automatically after this many process() calls (then never again
        # unless more hits are queued via fire() / detections).
        fire_after_frames: int | None = None,
    ) -> None:
        self._frame_length = frame_length
        self._queue: deque[Detection | None] = deque()
        if detections is not None:
            for item in detections:
                self._queue.append(self._normalize(item))
        self._fire_after_initial = fire_after_frames
        self._fire_after = fire_after_frames
        self._frames_seen = 0
        self.process_calls = 0
        self.closed = False
        self.reset_calls = 0

    @staticmethod
    def _normalize(item: bool | Detection | None) -> Detection | None:
        if item is True:
            return Detection(detector="fake", score=1.0)
        if item is False or item is None:
            return None
        return item

    @property
    def frame_length(self) -> int:
        return self._frame_length

    def fire(self, detection: Detection | None = None) -> None:
        """Enqueue a positive detection (or explicit None)."""
        self._queue.append(
            detection
            if detection is not None
            else Detection(detector="fake", score=1.0)
        )

    def process(self, frame_i16: Any) -> Detection | None:  # noqa: ARG002
        self.process_calls += 1
        self._frames_seen += 1
        if self._queue:
            return self._queue.popleft()
        if self._fire_after is not None and self._frames_seen >= self._fire_after:
            self._fire_after = None  # one-shot
            return Detection(detector="fake", score=1.0)
        return None

    def reset(self) -> None:
        """Clear between arming cycles; re-arm fire_after_frames if configured."""
        self.reset_calls += 1
        self._frames_seen = 0
        if self._fire_after_initial is not None:
            self._fire_after = self._fire_after_initial

    def close(self) -> None:
        self.closed = True


def silence_frames(
    n: int,
    *,
    frame_length: int = 512,
) -> list[np.ndarray]:
    """Generate n int16 silence frames for feeding FakeWakeDetector in tests."""
    return [np.zeros(frame_length, dtype=np.int16) for _ in range(n)]
