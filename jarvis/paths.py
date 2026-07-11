"""Well-known paths under the user's JARVIS home directory.

Default root: ``%USERPROFILE%\\.jarvis`` (override with ``JARVIS_HOME``).
"""

from __future__ import annotations

import os
from pathlib import Path


def jarvis_home() -> Path:
    """Root for user-owned JARVIS state (settings, audit log, TTS cache, …)."""
    env = os.environ.get("JARVIS_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".jarvis").resolve()


def default_settings_path() -> Path:
    return jarvis_home() / "settings.json"


def default_audit_log_path() -> Path:
    return jarvis_home() / "audit.log"
