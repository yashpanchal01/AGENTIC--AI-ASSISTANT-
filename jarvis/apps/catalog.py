"""Known desktop apps: spoken name → process stems + how to launch."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSpec:
    """One app the smart-open path knows about."""

    key: str  # canonical id, e.g. "brave"
    spoken: tuple[str, ...]  # aliases the user might say
    processes: tuple[str, ...]  # exe stems to detect running windows
    # Candidate launch argv lists, tried in order (first that exists wins).
    launch_candidates: tuple[tuple[str, ...], ...] = ()
    # Optional shell command if no candidate path works (Windows ``start``).
    shell_start: str | None = None


def _pf() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files"))


def _pf86() -> Path:
    return Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))


def _local() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", ""))


def default_catalog() -> tuple[AppSpec, ...]:
    la = _local()
    pf = _pf()
    pf86 = _pf86()
    return (
        AppSpec(
            key="brave",
            spoken=("brave", "brave browser"),
            processes=("brave",),
            launch_candidates=(
                (str(la / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),),
                (str(pf / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),),
                (str(pf86 / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),),
                ("brave",),
            ),
            shell_start="brave",
        ),
        AppSpec(
            key="chrome",
            spoken=("chrome", "google chrome"),
            processes=("chrome",),
            launch_candidates=(
                (str(pf / "Google" / "Chrome" / "Application" / "chrome.exe"),),
                (str(pf86 / "Google" / "Chrome" / "Application" / "chrome.exe"),),
                ("chrome",),
            ),
            shell_start="chrome",
        ),
        AppSpec(
            key="edge",
            spoken=("edge", "microsoft edge"),
            processes=("msedge",),
            launch_candidates=(
                (str(pf / "Microsoft" / "Edge" / "Application" / "msedge.exe"),),
                ("msedge",),
            ),
            shell_start="msedge",
        ),
        AppSpec(
            key="firefox",
            spoken=("firefox", "mozilla firefox"),
            processes=("firefox",),
            launch_candidates=(
                (str(pf / "Mozilla Firefox" / "firefox.exe"),),
                ("firefox",),
            ),
            shell_start="firefox",
        ),
        AppSpec(
            key="notepad",
            spoken=("notepad",),
            processes=("notepad",),
            launch_candidates=(("notepad.exe",), ("notepad",)),
            shell_start="notepad",
        ),
        AppSpec(
            key="spotify",
            spoken=("spotify",),
            processes=("spotify",),
            launch_candidates=(
                (str(la / "Microsoft" / "WindowsApps" / "Spotify.exe"),),
                (str(pf / "Spotify" / "Spotify.exe"),),
                ("spotify",),
            ),
            shell_start="spotify",
        ),
        AppSpec(
            key="vlc",
            spoken=("vlc", "vlc player"),
            processes=("vlc",),
            launch_candidates=(
                (str(pf86 / "VideoLAN" / "VLC" / "vlc.exe"),),
                (str(pf / "VideoLAN" / "VLC" / "vlc.exe"),),
                ("vlc",),
            ),
            shell_start="vlc",
        ),
        AppSpec(
            key="discord",
            spoken=("discord",),
            processes=("discord", "Discord"),
            launch_candidates=(
                (str(la / "Discord" / "Update.exe"), "--processStart", "Discord.exe"),
                ("discord",),
            ),
            shell_start="discord",
        ),
        AppSpec(
            key="code",
            spoken=("vs code", "vscode", "visual studio code", "code"),
            processes=("code", "Code"),
            launch_candidates=(("code",),),
            shell_start="code",
        ),
        AppSpec(
            key="calculator",
            spoken=("calculator", "calc"),
            processes=("calculatorapp", "win32calc", "calc"),
            launch_candidates=(("calc.exe",),),
            shell_start="calc",
        ),
        AppSpec(
            key="explorer",
            spoken=("file explorer", "explorer", "files"),
            processes=("explorer",),
            launch_candidates=(("explorer.exe",),),
            shell_start="explorer",
        ),
        AppSpec(
            key="terminal",
            spoken=("terminal", "windows terminal", "wt"),
            processes=("windowsterminal", "WindowsTerminal"),
            launch_candidates=(("wt.exe",), ("wt",)),
            shell_start="wt",
        ),
        AppSpec(
            key="settings",
            spoken=("settings", "windows settings"),
            processes=("systemsettings",),
            launch_candidates=(("cmd", "/c", "start", "ms-settings:"),),
            shell_start=None,
        ),
    )


def resolve_app(name: str, catalog: tuple[AppSpec, ...] | None = None) -> AppSpec | None:
    """Match spoken *name* to a catalog entry (longest alias wins)."""
    cat = catalog or default_catalog()
    raw = " ".join((name or "").lower().split())
    if not raw:
        return None
    best: AppSpec | None = None
    best_len = -1
    for spec in cat:
        for alias in spec.spoken:
            a = alias.lower()
            if raw == a or raw.endswith(" " + a) or raw.startswith(a + " "):
                if len(a) > best_len:
                    best, best_len = spec, len(a)
            # bare equality after stripping "the" / "app"
            cleaned = raw.removeprefix("the ").removesuffix(" app").removesuffix(" browser").strip()
            if cleaned == a and len(a) > best_len:
                best, best_len = spec, len(a)
    return best
