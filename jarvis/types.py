"""Shared domain types for the headless core loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Action:
    """An action the brain performed (or attempted) while handling a command."""

    name: str
    detail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrainTurn:
    """One turn of brain output for a single command.

    ``denied`` — hard refuse (secrets, policy). No confirmation offered.
    ``needs_confirmation`` — ask-first tier: propose ``proposed_action``, execute
    only after an explicit yes (core re-asks with a CONFIRMED: prefix).
    """

    reply: str
    actions: tuple[Action, ...] = ()
    session_id: str | None = None
    denied: bool = False
    needs_confirmation: bool = False
    proposed_action: str | None = None
    ok: bool = True
    error: str | None = None
