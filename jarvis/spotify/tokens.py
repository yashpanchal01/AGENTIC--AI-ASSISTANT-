"""Spotify token storage — same secure store as Google, never in memory notes."""

from __future__ import annotations

import os
from pathlib import Path

# The guarded JSON store is provider-agnostic; reuse it so Spotify tokens get
# the identical hard guard against the human-readable memory-notes tree.
from jarvis.google.tokens import TokenStore, memory_notes_dir

__all__ = ["TokenStore", "default_spotify_token_path", "memory_notes_dir", "spotify_token_store"]


def default_spotify_token_path() -> Path:
    """OS-local app data path for Spotify OAuth tokens (outside memory notes)."""
    env = os.environ.get("JARVIS_SPOTIFY_TOKEN")
    if env:
        return Path(env).expanduser().resolve()

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return (Path(base) / "Jarvis" / "spotify_token.json").resolve()
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return (Path(xdg) / "jarvis" / "spotify_token.json").resolve()
    return (Path.home() / ".local" / "state" / "jarvis" / "spotify_token.json").resolve()


def spotify_token_store(path: Path | None = None) -> TokenStore:
    """Token store at *path* (default OS app-data), guarded from memory notes."""
    return TokenStore(path=path or default_spotify_token_path())
