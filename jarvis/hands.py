"""Gated shell + file execution for the brain's hands (issue 21).

The bridge's ``run_command`` / ``file_op`` tools execute HERE — but only
after :mod:`jarvis.brain.shell_policy` has classified the call and the
bridge's confirm gate has said yes. This module never decides risk; it only
runs what was already allowed/confirmed, honestly reports the outcome, and
keeps output small enough for the model to read.

Implementation choices
----------------------
Real OS access is isolated behind the ``default_*`` functions so tests fake
every hand (same seam pattern as :mod:`jarvis.perception`):

* shell commands run through one ``powershell.exe -NoProfile -NonInteractive
  -Command`` subprocess with a hard timeout — no REPLs, no console window;
* **delete goes to the Recycle Bin, never a hard delete**, via ctypes
  ``SHFileOperationW`` (``FO_DELETE`` + ``FOF_ALLOWUNDO``). Chosen over the
  PowerShell route because it is stdlib-only like the repo's existing Win32
  layer (:mod:`jarvis.windows.win32api`) — the PowerShell equivalent must
  spawn a subprocess and load the Microsoft.VisualBasic assembly just to
  reach the same shell API;
* move/copy/mkdir ride ``shutil``/``pathlib``; zip/unzip ride stdlib
  ``zipfile`` (whose ``extract`` sanitizes ``..``/drive components, so a
  hostile archive cannot escape the destination folder).

Output discipline: stdout/stderr are truncated to ``MAX_OUTPUT_LINES`` /
``MAX_OUTPUT_CHARS`` — the model pays tokens for every byte (same rationale
as perception's ``MAX_ROWS``).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Hard caps on what one command may return to the model (token discipline).
MAX_OUTPUT_CHARS = 4000
MAX_OUTPUT_LINES = 50

# Timeout kills the command — no interactive/long-running processes.
DEFAULT_TIMEOUT_S = 60
MAX_TIMEOUT_S = 300

# Windows: run PowerShell without popping a console window.
_CREATE_NO_WINDOW = 0x08000000


class HandsError(RuntimeError):
    """Speakable failure from a hands adapter."""


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandOutput:
    """Raw output of one shell command (what the run adapter returns)."""

    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False


@dataclass(frozen=True)
class HandsResult:
    """One run_command / file_op outcome: text the model reads, plus status."""

    reply: str
    ok: bool = True
    error: str | None = None


# ---------------------------------------------------------------------------
# Real-OS adapters (fakeable; only exercised under ``pytest -m os_smoke``)
# ---------------------------------------------------------------------------


def default_run_shell(command: str, cwd: Path, timeout_s: int) -> CommandOutput:
    """One PowerShell command, captured and bounded; timeout kills it."""
    args = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        command,
    ]
    creationflags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            cwd=str(cwd),
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return CommandOutput(stdout="", stderr="", returncode=-1, timed_out=True)
    return CommandOutput(
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        returncode=proc.returncode,
    )


def default_recycle_delete(path: Path) -> None:
    """Send *path* to the Recycle Bin (never a hard delete).

    ctypes ``SHFileOperationW`` with ``FO_DELETE | FOF_ALLOWUNDO`` — the
    Windows shell's own recycle operation, stdlib-only (see module docstring
    for why this beats the PowerShell/VisualBasic route).
    """
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = (
            ("hwnd", wintypes.HWND),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        )

    FO_DELETE = 3
    FOF_SILENT = 0x0004
    FOF_NOCONFIRMATION = 0x0010  # JARVIS already confirmed; no OS dialog too
    FOF_ALLOWUNDO = 0x0040  # THE point: recycle, don't destroy
    FOF_NOERRORUI = 0x0400

    op = SHFILEOPSTRUCTW(
        hwnd=None,
        wFunc=FO_DELETE,
        # pFrom is a double-null-terminated list; c_wchar_p adds one null.
        pFrom=str(path) + "\0",
        pTo=None,
        fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI,
    )
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        raise HandsError(f"The Recycle Bin refused {path.name}.")


def default_move(src: Path, dst: Path) -> None:
    shutil.move(str(src), str(dst))


def default_copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def default_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def default_zip(src: Path, dst: Path) -> None:
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        if src.is_dir():
            for p in sorted(src.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(src))
        else:
            zf.write(src, src.name)


def default_unzip(src: Path, dst: Path) -> None:
    with zipfile.ZipFile(src) as zf:
        # zipfile.extract sanitizes '..' and drive components — no zip-slip.
        zf.extractall(dst)


def default_jail_roots(config: Any = None) -> tuple[Path, ...]:
    """The file_op path jail: config.approved_folders + profile folders."""
    roots: list[Path] = []
    if config is not None:
        roots.extend(Path(p) for p in getattr(config, "approved_folders", ()) or ())
    home = Path.home()
    for name in ("Downloads", "Desktop", "Documents", "Videos"):
        folder = home / name
        if folder not in roots:
            roots.append(folder)
    return tuple(roots)


# ---------------------------------------------------------------------------
# Hands
# ---------------------------------------------------------------------------

RunShellFn = Callable[[str, Path, int], CommandOutput]
PathFn = Callable[[Path], None]
PathPairFn = Callable[[Path, Path], None]


@dataclass
class Hands:
    """The gated hands behind run_command / file_op.

    ``roots`` is the file_op path jail (the bridge also hands it to the
    policy); every OS-touching function is injected so tests fake all of it.
    Nothing here checks risk — that already happened in shell_policy plus the
    bridge's confirm gate before any of these methods run.
    """

    roots: tuple[Path, ...] = ()
    cwd: Path | None = None  # default working directory for run_command
    run_shell: RunShellFn = default_run_shell
    move_fn: PathPairFn = default_move
    copy_fn: PathPairFn = default_copy
    mkdir_fn: PathFn = default_mkdir
    zip_fn: PathPairFn = default_zip
    unzip_fn: PathPairFn = default_unzip
    recycle_fn: PathFn = default_recycle_delete
    calls: list[tuple[str, ...]] = field(default_factory=list, repr=False)

    # -- shell ----------------------------------------------------------------

    def run_command(
        self, command: str, *, cwd: str | None = None, timeout_s: int | None = None
    ) -> HandsResult:
        directory = Path(cwd).expanduser() if cwd else (self.cwd or Path.cwd())
        timeout = _clamp_timeout(timeout_s)
        self.calls.append(("run", command, str(directory)))
        try:
            out = self.run_shell(command, directory, timeout)
        except OSError as exc:
            raise HandsError("I couldn't start that command.") from exc
        if out.timed_out:
            return HandsResult(
                reply=f"That command timed out after {timeout} seconds.",
                ok=False,
                error="timeout",
            )
        ok = out.returncode == 0
        return HandsResult(
            reply=_format_output(out),
            ok=ok,
            error=None if ok else f"exit_{out.returncode}",
        )

    # -- file operations --------------------------------------------------------

    def file_op(self, op: str, src: str, dst: str | None = None) -> HandsResult:
        kind = (op or "").strip().lower()
        src_path = Path(src).expanduser()
        dst_path = Path(dst).expanduser() if dst else None
        self.calls.append(("file_op", kind, str(src_path), str(dst_path or "")))
        try:
            return self._apply(kind, src_path, dst_path)
        except HandsError as exc:
            return HandsResult(reply=str(exc), ok=False, error="op_failed")
        except (OSError, shutil.Error, zipfile.BadZipFile) as exc:
            return HandsResult(
                reply=f"I couldn't {kind} that: {type(exc).__name__}.",
                ok=False,
                error="op_failed",
            )

    def _apply(self, kind: str, src: Path, dst: Path | None) -> HandsResult:
        if kind == "mkdir":
            self.mkdir_fn(src)
            return HandsResult(reply=f"Created folder {src.name}.")
        if kind == "delete":
            self.recycle_fn(src)
            return HandsResult(reply=f"Deleted {src.name} to the Recycle Bin.")
        assert dst is not None  # policy guaranteed a dst for the pair ops
        if kind in ("move", "rename"):
            self.move_fn(src, dst)
            verb = "Moved" if kind == "move" else "Renamed"
            return HandsResult(reply=f"{verb} {src.name} to {dst}.")
        if kind == "copy":
            self.copy_fn(src, dst)
            return HandsResult(reply=f"Copied {src.name} to {dst}.")
        if kind == "zip":
            self.zip_fn(src, dst)
            return HandsResult(reply=f"Zipped {src.name} to {dst}.")
        if kind == "unzip":
            self.unzip_fn(src, dst)
            return HandsResult(reply=f"Unzipped {src.name} to {dst}.")
        return HandsResult(
            reply=f"I don't know the file operation '{kind}'.",
            ok=False,
            error="unknown_op",
        )


def build_hands(config: Any = None) -> Hands:
    """Wire the hands from config (approved folders + cwd), real adapters."""
    cwd = Path(getattr(config, "cwd", None) or Path.cwd()) if config else Path.cwd()
    return Hands(roots=default_jail_roots(config), cwd=cwd)


# ---------------------------------------------------------------------------
# Formatting helpers (compact, capped — token discipline)
# ---------------------------------------------------------------------------


def _clamp_timeout(timeout_s: int | None) -> int:
    if timeout_s is None:
        return DEFAULT_TIMEOUT_S
    return max(1, min(MAX_TIMEOUT_S, int(timeout_s)))


def _format_output(out: CommandOutput) -> str:
    body = _trunc_block(out.stdout)
    err = _trunc_block(out.stderr)
    if err:
        body = f"{body}\nstderr:\n{err}" if body else f"stderr:\n{err}"
    if not body:
        body = "(no output)"
    return f"exit {out.returncode}\n{body}"


def _trunc_block(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) > MAX_OUTPUT_LINES:
        hidden = len(lines) - MAX_OUTPUT_LINES
        lines = lines[:MAX_OUTPUT_LINES] + [f"… (+{hidden} more lines)"]
    block = "\n".join(lines)
    if len(block) > MAX_OUTPUT_CHARS:
        block = block[: MAX_OUTPUT_CHARS - 1].rstrip() + "…"
    return block


__all__ = [
    "CommandOutput",
    "DEFAULT_TIMEOUT_S",
    "Hands",
    "HandsError",
    "HandsResult",
    "MAX_OUTPUT_CHARS",
    "MAX_OUTPUT_LINES",
    "MAX_TIMEOUT_S",
    "build_hands",
    "default_jail_roots",
    "default_recycle_delete",
    "default_run_shell",
    "default_zip",
]
