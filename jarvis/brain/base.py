"""Brain protocol — the provider-swappable seam for the core loop."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from jarvis.types import BrainTurn


@runtime_checkable
class Brain(Protocol):
    """Text in → reply + actions. Implementations own session persistence."""

    def ask(self, command: str) -> BrainTurn:
        """Handle one user command within the long-lived conversation."""
        ...
