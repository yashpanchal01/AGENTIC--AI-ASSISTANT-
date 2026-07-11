"""Google workspace seam: utterance → spoken reply + actions (or None)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from jarvis.types import Action


@dataclass(frozen=True)
class GoogleResult:
    """Outcome of a Gmail/Calendar intent (read or explicit refusal)."""

    reply: str
    actions: tuple[Action, ...] = ()
    denied: bool = False
    ok: bool = True
    error: str | None = None


@runtime_checkable
class GoogleWorkspace(Protocol):
    """One OAuth-backed hub for Gmail + Calendar voice queries."""

    def try_handle(self, utterance: str) -> GoogleResult | None:
        """Handle a gmail/calendar utterance, or return None if unrelated."""
        ...
