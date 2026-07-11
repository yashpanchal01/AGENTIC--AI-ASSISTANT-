"""Secure token storage — never under human-readable memory notes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def memory_notes_dir() -> Path:
    """Directory reserved for human-editable long-term memory (issue 07).

    Tokens must never live here or under it.
    """
    env = os.environ.get("JARVIS_MEMORY_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".jarvis" / "memory").resolve()


def default_token_path() -> Path:
    """OS-local app data path for Google OAuth tokens (outside memory notes)."""
    env = os.environ.get("JARVIS_GOOGLE_TOKEN")
    if env:
        return Path(env).expanduser().resolve()

    # Prefer platform app-data roots so tokens stay out of the repo and notes.
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return (Path(base) / "Jarvis" / "google_token.json").resolve()
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return (Path(xdg) / "jarvis" / "google_token.json").resolve()
    return (Path.home() / ".local" / "state" / "jarvis" / "google_token.json").resolve()


class TokenStore:
    """JSON token file with a hard guard against the memory-notes tree."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        memory_notes_root: Path | None = None,
    ) -> None:
        self.path = (path or default_token_path()).resolve()
        self.memory_notes_root = (memory_notes_root or memory_notes_dir()).resolve()
        if not self.is_safe_path(self.path, memory_notes_root=self.memory_notes_root):
            raise ValueError(
                f"Refusing to store Google tokens under memory notes "
                f"({self.memory_notes_root}): {self.path}"
            )

    @staticmethod
    def is_safe_path(path: Path, *, memory_notes_root: Path) -> bool:
        """True if *path* is not inside the human-readable memory notes tree."""
        try:
            resolved = path.resolve()
            root = memory_notes_root.resolve()
        except OSError:
            return False
        if resolved == root:
            return False
        try:
            resolved.relative_to(root)
            return False
        except ValueError:
            return True

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, sort_keys=True)
        self.path.write_text(text, encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass  # Windows may ignore POSIX mode bits

    def load(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        raw = self.path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Token file is not a JSON object: {self.path}")
        return data

    def clear(self) -> None:
        if self.path.is_file():
            self.path.unlink()
