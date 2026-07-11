"""Speaker protocol — TTS seam for spoken replies."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Speaker(Protocol):
    def speak(self, text: str) -> None:
        """Speak reply text aloud (or record it, for fakes)."""
        ...
