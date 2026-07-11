"""Memory seam: utterance → spoken reply + actions (or None)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from jarvis.types import Action


@dataclass(frozen=True)
class MemoryResult:
    """Outcome of a memory intent (remember / recall / forget or refusal)."""

    reply: str
    actions: tuple[Action, ...] = ()
    denied: bool = False
    ok: bool = True
    error: str | None = None


@runtime_checkable
class MemoryHandler(Protocol):
    """Markdown long-term memory for facts that must outlive sessions."""

    def try_handle(self, utterance: str) -> MemoryResult | None:
        """Handle a memory utterance, or return None if unrelated."""
        ...
