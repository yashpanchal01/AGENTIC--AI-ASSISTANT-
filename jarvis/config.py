"""JARVIS configuration for the headless core loop."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Safe-tier tools: auto-run with zero prompts (prototype-validated list).
# Destructive/outward tools are simply omitted → denied, never prompted.
DEFAULT_SAFE_TOOLS: tuple[str, ...] = (
    "Bash",
    "Read",
    "Glob",
    "Grep",
    "Write",
    "Edit",
    "WebSearch",
    "WebFetch",
)

JARVIS_SYSTEM_PROMPT = (
    "You are JARVIS, a voice-driven Windows assistant. "
    "Act immediately on the command with reasonable assumptions; "
    "never ask clarifying questions unless the action is destructive or irreversible. "
    "Launching apps, opening browser tabs/terminals, and file operations in the "
    "user's approved folders are pre-approved. "
    "If a shell command is blocked by the sandbox, retry it with the sandbox disabled. "
    "Never read, store, or speak passwords, API keys, or credentials. "
    "Reply in one short spoken-style sentence when done."
)


def _default_approved_folders() -> tuple[Path, ...]:
    home = Path.home()
    candidates = [
        home / "Documents",
        home / "Downloads",
        home / "Desktop",
        Path.cwd(),
    ]
    return tuple(p for p in candidates if p.exists())


def _default_piper_model() -> Path | None:
    env = os.environ.get("JARVIS_PIPER_MODEL")
    if env:
        p = Path(env)
        return p if p.exists() else None
    downloads = Path.home() / "Downloads" / "en_GB-northern_english_male-medium.onnx"
    if downloads.exists():
        return downloads
    return None


def _default_piper_exe() -> str:
    env = os.environ.get("JARVIS_PIPER_EXE")
    if env:
        return env
    # Prefer a known local install from the headless-loop setup path.
    local = Path.home() / ".local" / "piper" / "piper" / "piper.exe"
    if local.is_file():
        return str(local)
    return "piper"


@dataclass
class JarvisConfig:
    """Runtime config. Override fields or construct from env."""

    approved_folders: tuple[Path, ...] = field(default_factory=_default_approved_folders)
    safe_tools: tuple[str, ...] = DEFAULT_SAFE_TOOLS
    claude_model: str = "sonnet"
    claude_bin: str = "claude"
    permission_mode: str = "acceptEdits"
    system_prompt: str = JARVIS_SYSTEM_PROMPT
    cwd: Path = field(default_factory=Path.cwd)
    piper_exe: str = field(default_factory=_default_piper_exe)
    piper_model: Path | None = field(default_factory=_default_piper_model)
    speak: bool = True

    @classmethod
    def from_env(cls) -> JarvisConfig:
        model = os.environ.get("JARVIS_MODEL", "sonnet")
        speak = os.environ.get("JARVIS_SPEAK", "1") not in ("0", "false", "no")
        return cls(claude_model=model, speak=speak)
