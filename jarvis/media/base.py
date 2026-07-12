"""Local media result type (same shape as Spotify/Memory for core._finish_handler)."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.types import Action


@dataclass
class MediaResult:
    reply: str
    actions: tuple[Action, ...] = ()
    denied: bool = False
    ok: bool = True
    error: str | None = None
