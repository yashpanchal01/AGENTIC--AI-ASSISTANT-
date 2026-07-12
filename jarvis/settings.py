"""User settings file — hotkey, approved folders, voice (no code edits).

Default path: ``%USERPROFILE%\\.jarvis\\settings.json`` (see :func:`jarvis.paths.default_settings_path`).

Example::

    {
      "hotkey": "ctrl+shift+j",
      "approved_folders": [
        "C:\\\\Users\\\\You\\\\Documents",
        "C:\\\\Users\\\\You\\\\Downloads"
      ],
      "voice": "C:\\\\Users\\\\You\\\\Downloads\\\\en_GB-northern_english_male-medium.onnx",
      "piper_model": null,
      "enable_hotkey": true
    }

``voice`` and ``piper_model`` are aliases for the Piper ONNX model path.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from jarvis.paths import default_settings_path


@dataclass(frozen=True)
class UserSettings:
    """Subset of preferences the user owns (issue 11 / US-36)."""

    hotkey: str | None = None
    enable_hotkey: bool | None = None
    approved_folders: tuple[Path, ...] | None = None
    # Piper ONNX model path (voice identity).
    voice: Path | None = None
    # Optional explicit piper binary (advanced).
    piper_exe: str | None = None
    # Spotify developer-app client ID (issue 09) — an ID, not a secret.
    spotify_client_id: str | None = None
    raw: dict[str, Any] | None = None


def load_settings(path: Path | None = None) -> UserSettings:
    """Load settings from *path* (or the default). Missing / empty → empty settings.

    Corrupt or unreadable files warn once on stderr and fall back to empty
    settings so startup never crashes.
    """
    import sys

    settings_path = path if path is not None else default_settings_path()
    if not settings_path.is_file():
        return UserSettings()
    try:
        # utf-8-sig strips a Windows/Notepad BOM so hand-edited settings load.
        text = settings_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(
            f"JARVIS> settings: could not read {settings_path}: {exc}",
            file=sys.stderr,
        )
        return UserSettings()
    text = text.strip()
    if not text:
        print(
            f"JARVIS> settings: empty file {settings_path} — using defaults",
            file=sys.stderr,
        )
        return UserSettings()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(
            f"JARVIS> settings: invalid JSON in {settings_path}: {exc} — using defaults",
            file=sys.stderr,
        )
        return UserSettings()
    if not isinstance(data, dict):
        print(
            f"JARVIS> settings: expected a JSON object in {settings_path} — using defaults",
            file=sys.stderr,
        )
        return UserSettings()
    return parse_settings_dict(data)


def parse_settings_dict(data: dict[str, Any]) -> UserSettings:
    """Parse a settings mapping (also used by tests)."""
    hotkey = data.get("hotkey")
    if hotkey is not None:
        hotkey = str(hotkey).strip() or None

    enable_hotkey = data.get("enable_hotkey")
    if enable_hotkey is not None:
        if isinstance(enable_hotkey, str):
            enable_hotkey = enable_hotkey.strip().lower() not in (
                "0",
                "false",
                "no",
                "off",
            )
        else:
            enable_hotkey = bool(enable_hotkey)

    folders: tuple[Path, ...] | None = None
    raw_folders = data.get("approved_folders")
    if raw_folders is not None:
        if isinstance(raw_folders, (str, Path)):
            raw_folders = [raw_folders]
        if isinstance(raw_folders, (list, tuple)):
            parsed: list[Path] = []
            for item in raw_folders:
                p = Path(str(item)).expanduser()
                parsed.append(p)
            folders = tuple(parsed)

    voice: Path | None = None
    for key in ("voice", "piper_model", "voice_model"):
        if data.get(key):
            voice = Path(str(data[key])).expanduser()
            break

    piper_exe = data.get("piper_exe")
    if piper_exe is not None:
        piper_exe = str(piper_exe).strip() or None

    spotify_client_id = data.get("spotify_client_id")
    if spotify_client_id is not None:
        spotify_client_id = str(spotify_client_id).strip() or None

    return UserSettings(
        hotkey=hotkey,
        enable_hotkey=enable_hotkey,
        approved_folders=folders,
        voice=voice,
        piper_exe=piper_exe,
        spotify_client_id=spotify_client_id,
        raw=dict(data),
    )


def apply_user_settings(config: Any, settings: UserSettings | None = None) -> Any:
    """Return a copy of *config* with user settings applied.

    Settings override defaults/env for: hotkey, enable_hotkey, approved_folders,
    piper_model (voice), piper_exe. Call after :meth:`JarvisConfig.from_env`.
    """
    if settings is None:
        settings = load_settings()
    updates: dict[str, Any] = {}
    if settings.hotkey is not None:
        updates["hotkey"] = settings.hotkey
    if settings.enable_hotkey is not None:
        updates["enable_hotkey"] = settings.enable_hotkey
    if settings.approved_folders is not None:
        updates["approved_folders"] = settings.approved_folders
    if settings.voice is not None:
        updates["piper_model"] = settings.voice
    if settings.piper_exe is not None:
        updates["piper_exe"] = settings.piper_exe
    if settings.spotify_client_id is not None:
        updates["spotify_client_id"] = settings.spotify_client_id
    if not updates:
        return config
    # Dataclass replace keeps identity of other fields.
    return replace(config, **updates)


def settings_path_from_env() -> Path:
    """Allow ``JARVIS_SETTINGS`` to point at an alternate file."""
    env = os.environ.get("JARVIS_SETTINGS")
    if env:
        return Path(env).expanduser().resolve()
    return default_settings_path()


def load_settings_for_config() -> UserSettings:
    """Load from ``JARVIS_SETTINGS`` or the default path."""
    return load_settings(settings_path_from_env())
