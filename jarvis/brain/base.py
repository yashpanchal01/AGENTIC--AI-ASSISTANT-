"""Brain protocol — the provider-swappable seam for the core loop."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from jarvis.types import BrainTurn


@runtime_checkable
class Brain(Protocol):
    """Text in → reply + actions. Implementations own session persistence.

    ``confirmed=True`` is set only by the core after an explicit user yes on
    the ask-first gate. User text must never be treated as already confirmed.
    """

    def ask(self, command: str, *, confirmed: bool = False) -> BrainTurn:
        """Handle one user command within the long-lived conversation."""
        ...
