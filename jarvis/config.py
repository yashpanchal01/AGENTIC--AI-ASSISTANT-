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
    "Gmail and Calendar are handled by JARVIS itself (read-only); do not send, "
    "reply, forward email or create calendar events. "
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


def _default_whisper_model() -> str:
    return os.environ.get(
        "JARVIS_WHISPER_MODEL",
        "distil-whisper/distil-large-v3.5-ct2",
    )


def _default_dictionary_path() -> Path | None:
    env = os.environ.get("JARVIS_DICTIONARY")
    if env:
        return Path(env)
    return None  # stt.dictionary.default_dictionary_path() used at runtime


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
    # STT / voice (issue 03)
    whisper_model: str = field(default_factory=_default_whisper_model)
    whisper_device: str = "cuda"
    whisper_compute: str = "int8_float16"
    dictionary_path: Path | None = field(default_factory=_default_dictionary_path)
    silence_duration_s: float = 0.8
    max_record_s: float = 30.0
    # Front door (issue 04)
    hotkey: str = "ctrl+shift+j"
    enable_hotkey: bool = True
    wake_threshold: float = 0.5
    wake_sensitivity: float = 0.5  # Porcupine
    picovoice_access_key: str | None = None  # default: env PICOVOICE_ACCESS_KEY
    # Google OAuth (issue 7) — paths only; tokens never under memory notes
    google_client_secrets: Path | None = None
    google_token_path: Path | None = None

    @classmethod
    def from_env(cls) -> JarvisConfig:
        model = os.environ.get("JARVIS_MODEL", "sonnet")
        speak = os.environ.get("JARVIS_SPEAK", "1") not in ("0", "false", "no")
        device = os.environ.get("JARVIS_WHISPER_DEVICE", "cuda")
        compute = os.environ.get("JARVIS_WHISPER_COMPUTE", "int8_float16")
        hotkey = os.environ.get("JARVIS_HOTKEY", "ctrl+shift+j")
        enable_hotkey = os.environ.get("JARVIS_HOTKEY_ENABLE", "1") not in (
            "0",
            "false",
            "no",
        )
        try:
            wake_threshold = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.5"))
        except ValueError:
            wake_threshold = 0.5
        try:
            wake_sensitivity = float(os.environ.get("JARVIS_WAKE_SENSITIVITY", "0.5"))
        except ValueError:
            wake_sensitivity = 0.5
        pico = os.environ.get("PICOVOICE_ACCESS_KEY") or None
        secrets = os.environ.get("JARVIS_GOOGLE_CLIENT_SECRETS")
        token = os.environ.get("JARVIS_GOOGLE_TOKEN")
        return cls(
            claude_model=model,
            speak=speak,
            whisper_device=device,
            whisper_compute=compute,
            hotkey=hotkey,
            enable_hotkey=enable_hotkey,
            wake_threshold=wake_threshold,
            wake_sensitivity=wake_sensitivity,
            picovoice_access_key=pico,
            google_client_secrets=Path(secrets) if secrets else None,
            google_token_path=Path(token) if token else None,
        )
