"""Read-only perception for the brain's ``observe_*`` bridge tools (issue 19).

The brain used to act blind: it could open/close/play but not SEE what is
open, running, playing, or recently downloaded — so "close that" or "what's
eating my RAM" could not work. This module is the four senses behind the
bridge's observe tools: open windows, running processes, recent files in a
named folder, and (via the Spotify slice, wired in the bridge) now playing.

Implementation choices
----------------------
Real OS access is isolated behind the ``default_*`` functions so tests fake
every sense (same seam pattern as issue 16's ``default_get_brightness``):

* windows ride the existing ctypes layer in :mod:`jarvis.windows.win32api`
  (EnumWindows plus small IsIconic/GetForegroundWindow additions);
* processes shell out to stdlib ``tasklist /fo csv`` — the same "call the OS,
  don't reimplement it" rationale as issue 16's brightness (ctypes
  EnumProcesses + GetProcessMemoryInfo is more code for no more truth, and
  ``psutil``/``pywin32`` are exactly the heavy deps this repo avoids);
* files reuse the one-level newest-by-mtime discipline of issue 16's
  :func:`jarvis.system.handler.find_latest`, generalized to a listing.

Output discipline: the model pays tokens for every byte it reads, so every
observation is compact lines capped at ``MAX_ROWS`` with long names truncated
to ``TITLE_MAX`` — never a huge dump.
"""

from __future__ import annotations

import csv
import io
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Hard caps on what one observation may return (token discipline).
MAX_ROWS = 25
TITLE_MAX = 60

# Windows: run tasklist without popping a console window.
_CREATE_NO_WINDOW = 0x08000000

PROCESS_LIST_FAILED = "I couldn't read the process list."


class PerceptionError(RuntimeError):
    """Speakable failure from a perception adapter."""


# ---------------------------------------------------------------------------
# Observation rows (what the fakeable adapters return)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowObs:
    """One visible top-level window."""

    title: str
    process: str  # lowercased exe stem, e.g. "chrome"
    pid: int
    minimized: bool = False
    focused: bool = False


@dataclass(frozen=True)
class ProcessObs:
    """One running process with its working-set RAM."""

    name: str  # image name, e.g. "chrome.exe"
    pid: int
    ram_kb: int


@dataclass(frozen=True)
class FileObs:
    """One plain file in an observed folder."""

    name: str
    size: int  # bytes
    mtime: float  # epoch seconds


@dataclass(frozen=True)
class Observation:
    """One observe_* outcome: compact text the model reads, plus status."""

    reply: str
    ok: bool = True
    error: str | None = None
    rows: int = 0


# ---------------------------------------------------------------------------
# Real-OS adapters (fakeable; only exercised under ``pytest -m os_smoke``)
# ---------------------------------------------------------------------------


def default_list_windows() -> list[WindowObs]:
    """Visible top-level windows via the existing ctypes Win32 layer."""
    from jarvis.windows.win32api import foreground_hwnd, is_minimized, list_windows

    fg = foreground_hwnd()
    return [
        WindowObs(
            title=w.title,
            process=w.process,
            pid=w.pid,
            minimized=is_minimized(w.hwnd),
            focused=(w.hwnd == fg),
        )
        for w in list_windows()
    ]


def default_list_processes() -> list[ProcessObs]:
    """Running processes via stdlib ``tasklist /fo csv`` (no psutil/pywin32)."""
    if sys.platform != "win32":
        raise PerceptionError("Process listing is only available on Windows.")
    try:
        proc = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PerceptionError(PROCESS_LIST_FAILED) from exc
    if proc.returncode != 0:
        raise PerceptionError(PROCESS_LIST_FAILED)
    out: list[ProcessObs] = []
    # Rows: "Image Name","PID","Session Name","Session#","Mem Usage"
    for row in csv.reader(io.StringIO(proc.stdout or "")):
        if len(row) < 5:
            continue
        try:
            pid = int(row[1])
        except ValueError:
            continue
        # Mem Usage like "12,345 K" — locale grouping varies, so keep digits.
        kb = "".join(ch for ch in row[4] if ch.isdigit())
        out.append(ProcessObs(name=row[0], pid=pid, ram_kb=int(kb or 0)))
    return out


def default_scan_files(root: Path) -> list[FileObs]:
    """Plain files directly under *root* (one level, like ``find_latest``).

    Missing or unreadable folder → empty list; the caller words the reply.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    out: list[FileObs] = []
    for p in entries:
        try:
            if not p.is_file():
                continue
            st = p.stat()
        except OSError:
            continue
        out.append(FileObs(name=p.name, size=int(st.st_size), mtime=st.st_mtime))
    return out


def default_named_roots() -> dict[str, Path]:
    """The everyday folders the model may name directly in ``observe_files``."""
    home = Path.home()
    return {
        "downloads": home / "Downloads",
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "videos": home / "Videos",
    }


# ---------------------------------------------------------------------------
# Observer
# ---------------------------------------------------------------------------

ListWindowsFn = Callable[[], list[WindowObs]]
ListProcessesFn = Callable[[], list[ProcessObs]]
ScanFilesFn = Callable[[Path], list[FileObs]]


@dataclass
class Observer:
    """The read-only senses behind observe_windows/processes/files.

    ``list_windows`` / ``list_processes`` / ``scan_files`` are injected so
    tests fake every sense without touching the real OS; ``named_roots`` and
    ``approved_roots`` come from config so folder access stays inside the
    same boundaries the rest of JARVIS honours.
    """

    named_roots: dict[str, Path] = field(default_factory=default_named_roots)
    approved_roots: tuple[Path, ...] = ()
    list_windows: ListWindowsFn = default_list_windows
    list_processes: ListProcessesFn = default_list_processes
    scan_files: ScanFilesFn = default_scan_files

    # -- windows --------------------------------------------------------------

    def observe_windows(
        self, *, process: str | None = None, title: str | None = None
    ) -> Observation:
        proc = (process or "").strip().lower()
        sub = (title or "").strip().lower()
        matched = [
            w
            for w in self.list_windows()
            if (not proc or proc in w.process)
            and (not sub or sub in w.title.lower())
        ]
        if not matched:
            return Observation(reply="No open windows matched.", rows=0)
        # Focused window first (stable otherwise) — it is what "that" means.
        matched.sort(key=lambda w: not w.focused)
        shown = matched[:MAX_ROWS]
        lines = [_count_header(len(matched), len(shown), "open windows")]
        for w in shown:
            flags = "".join(
                f" [{f}]"
                for f, on in (("focused", w.focused), ("minimized", w.minimized))
                if on
            )
            lines.append(
                f"- {w.process or '?'} (pid {w.pid}){flags}: {_trunc(w.title)}"
            )
        return Observation(reply="\n".join(lines), rows=len(shown))

    # -- processes ------------------------------------------------------------

    def observe_processes(
        self, *, name: str | None = None, limit: int | None = None
    ) -> Observation:
        sub = (name or "").strip().lower()
        matched = [
            p for p in self.list_processes() if not sub or sub in p.name.lower()
        ]
        if not matched:
            return Observation(reply="No running processes matched.", rows=0)
        matched.sort(key=lambda p: p.ram_kb, reverse=True)
        shown = matched[: _clamp_limit(limit)]
        lines = [_count_header(len(matched), len(shown), "processes by RAM")]
        lines.extend(
            f"- {_trunc(p.name)} (pid {p.pid}): {_fmt_ram(p.ram_kb)}" for p in shown
        )
        return Observation(reply="\n".join(lines), rows=len(shown))

    # -- files ----------------------------------------------------------------

    def observe_files(
        self, *, folder: str, ext: str | None = None, limit: int | None = None
    ) -> Observation:
        root, label, err = self._resolve_folder(folder)
        if root is None:
            return Observation(reply=label, ok=False, error=err)
        suffix = (ext or "").strip().lower()
        if suffix and not suffix.startswith("."):
            suffix = "." + suffix
        matched = [
            f
            for f in self.scan_files(root)
            if not suffix or f.name.lower().endswith(suffix)
        ]
        if not matched:
            return Observation(reply=f"No files found in {label}.", rows=0)
        matched.sort(key=lambda f: f.mtime, reverse=True)
        shown = matched[: _clamp_limit(limit)]
        lines = [
            _count_header(len(matched), len(shown), f"files in {label}, newest first")
        ]
        lines.extend(
            f"- {_trunc(f.name)} ({_fmt_size(f.size)}, {_fmt_mtime(f.mtime)})"
            for f in shown
        )
        return Observation(reply="\n".join(lines), rows=len(shown))

    def _resolve_folder(self, folder: str) -> tuple[Path | None, str, str | None]:
        """Resolve a folder arg → (root, spoken label, error code)."""
        text = (folder or "").strip()
        key = text.lower()
        if key in self.named_roots:
            return self.named_roots[key], key, None
        if not text or ("\\" not in text and "/" not in text and ":" not in text):
            # A bare word that is not a known folder name — never guess a path.
            names = ", ".join(self.named_roots) or "an approved folder path"
            return (
                None,
                f"I can only look in {names}, or an approved folder path.",
                "unknown_folder",
            )
        path = Path(text).expanduser()
        if not _is_within(path, self.approved_roots):
            return (
                None,
                "That folder isn't in your approved folders.",
                "folder_not_allowed",
            )
        return path, path.name or str(path), None


def build_observer(config: Any = None) -> Observer:
    """Wire the observer from config's approved folders (settings-driven)."""
    roots: tuple[Path, ...] = ()
    if config is not None:
        roots = tuple(Path(p) for p in getattr(config, "approved_folders", ()) or ())
    return Observer(approved_roots=roots)


# ---------------------------------------------------------------------------
# Formatting helpers (compact, capped — token discipline)
# ---------------------------------------------------------------------------


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return MAX_ROWS
    return max(1, min(MAX_ROWS, int(limit)))


def _trunc(text: str, limit: int = TITLE_MAX) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _count_header(total: int, shown: int, what: str) -> str:
    if shown < total:
        return f"{total} {what} (showing top {shown}):"
    return f"{total} {what}:"


def _fmt_ram(kb: int) -> str:
    mb = kb / 1024
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{mb:.0f} MB"


def _fmt_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            return f"{value:.0f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _fmt_mtime(mtime: float) -> str:
    try:
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "?"


def _is_within(path: Path, roots: tuple[Path, ...]) -> bool:
    """True if *path* is one of *roots* or inside one (Windows-case-insensitive)."""
    try:
        cand = path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            base = Path(root).resolve()
        except OSError:
            continue
        if cand == base or base in cand.parents:
            return True
    return False


__all__ = [
    "FileObs",
    "MAX_ROWS",
    "Observation",
    "Observer",
    "PerceptionError",
    "ProcessObs",
    "TITLE_MAX",
    "WindowObs",
    "build_observer",
    "default_list_processes",
    "default_list_windows",
    "default_named_roots",
    "default_scan_files",
]
