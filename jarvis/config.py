"""JARVIS configuration for the headless core loop."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Safe-tier tools: auto-run with zero prompts (prototype-validated list).
# Ask-first tier (issue 06) is enforced in core/brain before tools run for
# destructive/system/outward commands; secrets stay hard-denied always.
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
    "Destructive, system-level, or out-of-folder actions are gated by JARVIS itself "
    "before this prompt — if you are asked to perform one, the user already said "
    "yes; proceed with the action. "
    "Gmail and Calendar are read-only: you may summarize mail or the schedule, "
    "but never send, reply to, or forward email, and never create calendar events. "
    "When something fails (file not found, app missing, tool error), explain in "
    "one short plain sentence what went wrong and why — never fail silently, never "
    "return a stack trace, and never claim an action succeeded when it did not. "
    "Reply in one short spoken-style sentence when done."
)

# Appended for the Claude brain ONLY when the MCP tool bridge (issue 15) is
# active: it can call JARVIS's own tools, so it should prefer them over shell.
CLAUDE_TOOL_BRIDGE_GUIDANCE = (
    "You have JARVIS's own tools for these domains: spotify (music playback), "
    "apps (open/focus a desktop app), windows (focus/minimize/maximize/snap/close "
    "a window), media (play a local media file), system (screen brightness + "
    "open the last screen recording), memory (remember/recall/forget "
    "facts), and google_read (read-only Gmail and Calendar). Prefer these tools "
    "over raw shell commands for those domains — they are more reliable and speak "
    "the reply for you. For a multi-domain request, call them in order (e.g. open "
    "an app, then control its playback). google_read is read-only; JARVIS refuses "
    "to send, reply, forward email, or create calendar events."
)

# Appended for the Grok brain: it does NOT have the tool bridge (issue 15), so
# it must not pretend to call those tools or fake success.
GROK_NO_TOOL_BRIDGE_NOTE = (
    "Note: you do not have JARVIS's tool bridge — the spotify, apps, windows, "
    "media, memory, and google_read tools are available only to the primary "
    "Claude brain. Handle app/window/music/media requests with your normal shell "
    "tools where you can; if you cannot, say so plainly in one sentence and never "
    "pretend an action succeeded."
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


def _default_capture_folders() -> tuple[Path, ...]:
    """Folders scanned for "open the last screen recording" (newest by mtime).

    Override with ``JARVIS_CAPTURE_FOLDERS`` (os.pathsep-separated) or the
    ``capture_folders`` settings key. Defaults to the Windows Game Bar /
    screen-recording locations under the user's Videos folder.
    """
    env = os.environ.get("JARVIS_CAPTURE_FOLDERS")
    if env:
        parts = [p.strip() for p in env.split(os.pathsep) if p.strip()]
        if parts:
            return tuple(Path(p).expanduser() for p in parts)
    home = Path.home()
    return (
        home / "Videos" / "Captures",
        home / "Videos",
    )


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
    # Capture folders for "open the last screen recording" (issue 16).
    capture_folders: tuple[Path, ...] = field(default_factory=_default_capture_folders)
    safe_tools: tuple[str, ...] = DEFAULT_SAFE_TOOLS
    # Brain provider: "claude" (default — only brain with the MCP tool bridge, so
    # the only one that can actually act), "grok" (fallback), or "fake".
    brain_provider: str = "claude"
    claude_model: str = "sonnet"
    claude_bin: str = "claude"
    grok_bin: str = "grok"
    # Empty model → Grok CLI default (SuperGrok session). Set JARVIS_GROK_MODEL to pin.
    grok_model: str = ""
    # NOTE: the Grok tool allowlist lives in exactly one place —
    # jarvis.brain.grok_cli.DEFAULT_GROK_SAFE_TOOLS (the dead grok_safe_tools
    # key was removed in issue 13; stale settings.json keys are ignored).
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
    # Spotify (issue 09) — free developer-app client ID (PKCE, no secret).
    # None → not configured; music commands answer with a setup pointer.
    spotify_client_id: str | None = None
    spotify_token_path: Path | None = None
    # Markdown long-term memory (issue 07) — None → JARVIS_MEMORY_DIR or
    # ~/.jarvis/memory (see jarvis.memory.store.default_memory_dir).
    memory_dir: Path | None = None
    # Graceful degradation (issue 9)
    # Pre-check internet before calling the cloud brain (skip with JARVIS_CHECK_NET=0).
    check_connectivity: bool = True
    # Free Whisper VRAM between commands so games can coexist (JARVIS_UNLOAD_STT=1).
    unload_stt_between_commands: bool = False
    # Long tasks (issue 10): background brain turns that exceed this many seconds.
    long_task_threshold_s: float = 20.0
    # Overlay face (issue 18): "aurora" (default Mono pill) or "spine" (MK.I SPINE
    # instrument plate). Override with JARVIS_OVERLAY_STYLE or the settings key.
    overlay_style: str = "aurora"

    @classmethod
    def from_env(cls, *, apply_settings: bool = True) -> JarvisConfig:
        """Build config from defaults + environment, then user settings file.

        Order: dataclass defaults → env vars → ``~/.jarvis/settings.json``
        (hotkey, approved_folders, voice). Pass ``apply_settings=False`` to
        skip the settings file (tests / explicit CLI-only paths).
        """
        model = os.environ.get("JARVIS_MODEL", "sonnet")
        brain = os.environ.get("JARVIS_BRAIN", "claude").strip().lower()
        if brain not in ("grok", "claude", "fake"):
            brain = "claude"
        grok_model = os.environ.get("JARVIS_GROK_MODEL", "").strip()
        grok_bin = os.environ.get("JARVIS_GROK_BIN", "grok").strip() or "grok"
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
        spotify_id = (os.environ.get("JARVIS_SPOTIFY_CLIENT_ID") or "").strip() or None
        spotify_token = os.environ.get("JARVIS_SPOTIFY_TOKEN")
        memory_env = os.environ.get("JARVIS_MEMORY_DIR")
        check_net = os.environ.get("JARVIS_CHECK_NET", "1") not in (
            "0",
            "false",
            "no",
        )
        unload_stt = os.environ.get("JARVIS_UNLOAD_STT", "0") in (
            "1",
            "true",
            "yes",
        )
        try:
            long_thresh = float(os.environ.get("JARVIS_LONG_TASK_S", "20"))
        except ValueError:
            long_thresh = 20.0
        overlay_style = os.environ.get("JARVIS_OVERLAY_STYLE", "aurora").strip().lower()
        if overlay_style not in ("aurora", "spine"):
            overlay_style = "aurora"
        cfg = cls(
            brain_provider=brain,
            claude_model=model,
            grok_model=grok_model,
            grok_bin=grok_bin,
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
            spotify_client_id=spotify_id,
            spotify_token_path=Path(spotify_token) if spotify_token else None,
            memory_dir=Path(memory_env) if memory_env else None,
            check_connectivity=check_net,
            unload_stt_between_commands=unload_stt,
            long_task_threshold_s=long_thresh,
            overlay_style=overlay_style,
        )
        if apply_settings:
            from jarvis.settings import apply_user_settings, load_settings_for_config

            cfg = apply_user_settings(cfg, load_settings_for_config())
        return cfg
