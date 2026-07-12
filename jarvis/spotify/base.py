"""Spotify seam: utterance → spoken reply + actions (or None if unrelated)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from jarvis.types import Action


class SpotifyError(Exception):
    """A Spotify failure with a plain, speakable message.

    ``str(exc)`` is spoken to the user as-is — write messages in plain
    language ("Spotify isn't active on any device…"), never API jargon.
    """


@dataclass(frozen=True)
class SpotifyResult:
    """Outcome of a Spotify playback intent."""

    reply: str
    actions: tuple[Action, ...] = ()
    denied: bool = False
    ok: bool = True
    error: str | None = None


@runtime_checkable
class SpotifyControl(Protocol):
    """Voice-facing Spotify hub (mirror of GoogleWorkspace)."""

    def try_handle(self, utterance: str) -> SpotifyResult | None:
        """Handle a music utterance, or return None if unrelated."""
        ...
