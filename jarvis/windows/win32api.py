"""Minimal Win32 window helpers (ctypes only — no pywin32).

Used for: focus, minimize, maximize, restore, close, snap half-screen,
and true media fullscreen (VLC video fullscreen, not Windows maximize).
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

user32 = ctypes.windll.user32 if sys.platform == "win32" else None  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None  # type: ignore[attr-defined]

SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9
SW_SHOW = 5
SW_SHOWNOACTIVATE = 4
WM_CLOSE = 0x0010
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
VK_F = 0x46
VK_F11 = 0x7A
KEYEVENTF_KEYUP = 0x0002
HWND_TOP = 0
SWP_SHOWWINDOW = 0x0040
SWP_NOZORDER = 0x0004

# SPI / work area
SPI_GETWORKAREA = 0x0030


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    process: str  # lowercased exe stem, e.g. "vlc"


class WindowError(RuntimeError):
    """Speakable failure from the window layer."""


def _require_win() -> None:
    if user32 is None:
        raise WindowError("Window control is only available on Windows.")


def _enum_windows() -> list[tuple[int, str, int]]:
    """Return (hwnd, title, pid) for visible top-level windows with a title."""
    _require_win()
    results: list[tuple[int, str, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        results.append((int(hwnd), title, int(pid.value)))
        return True

    user32.EnumWindows(_cb, 0)
    return results


def _process_name(pid: int) -> str:
    """Best-effort exe stem for *pid* (e.g. ``vlc``). Empty on failure."""
    if kernel32 is None:
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(260)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        path = buf.value
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        if name.lower().endswith(".exe"):
            name = name[:-4]
        return name.lower()
    finally:
        kernel32.CloseHandle(handle)


def list_windows() -> list[WindowInfo]:
    out: list[WindowInfo] = []
    for hwnd, title, pid in _enum_windows():
        out.append(
            WindowInfo(
                hwnd=hwnd,
                title=title,
                pid=pid,
                process=_process_name(pid),
            )
        )
    return out


def find_windows(
    *,
    process: str | None = None,
    title_substr: str | None = None,
) -> list[WindowInfo]:
    """Filter visible windows by process name and/or title substring."""
    proc = (process or "").strip().lower()
    sub = (title_substr or "").strip().lower()
    hits: list[WindowInfo] = []
    for w in list_windows():
        if proc and proc != w.process and proc not in w.process:
            continue
        if sub and sub not in w.title.lower():
            continue
        hits.append(w)
    return hits


def _force_foreground(hwnd: int) -> None:
    """Best-effort SetForegroundWindow (Windows often blocks plain calls)."""
    _require_win()
    user32.ShowWindow(hwnd, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return
    cur_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    tgt_tid = user32.GetWindowThreadProcessId(hwnd, None)
    attached_fg = False
    attached_tgt = False
    try:
        if fg_tid and fg_tid != cur_tid:
            attached_fg = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
        if tgt_tid and tgt_tid != cur_tid:
            attached_tgt = bool(user32.AttachThreadInput(cur_tid, tgt_tid, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached_tgt:
            user32.AttachThreadInput(cur_tid, tgt_tid, False)
        if attached_fg:
            user32.AttachThreadInput(cur_tid, fg_tid, False)


def focus(hwnd: int) -> None:
    _force_foreground(hwnd)


def minimize(hwnd: int) -> None:
    _require_win()
    user32.ShowWindow(hwnd, SW_MINIMIZE)


# Shell / desktop hosts we never mass-minimize (would nuke the desktop).
_SKIP_MINIMIZE_ALL = frozenset(
    {
        "explorer",
        "shellexperiencehost",
        "startmenuexperiencehost",
        "searchhost",
        "searchapp",
        "textinputhost",
        "applicationframehost",  # often hosts system UI
        "systemsettings",
        "lockapp",
    }
)


def minimize_all(*, skip_processes: frozenset[str] | None = None) -> int:
    """Minimize every visible top-level app window. Returns count minimized."""
    _require_win()
    skip = skip_processes if skip_processes is not None else _SKIP_MINIMIZE_ALL
    n = 0
    for w in list_windows():
        if w.process in skip:
            continue
        title_l = w.title.lower()
        if title_l in ("program manager",):
            continue
        try:
            user32.ShowWindow(w.hwnd, SW_MINIMIZE)
            n += 1
        except Exception:
            continue
    return n


def maximize(hwnd: int) -> None:
    """Windows maximize (keeps title bar) — not VLC video fullscreen."""
    _require_win()
    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    _force_foreground(hwnd)


def restore(hwnd: int) -> None:
    _require_win()
    user32.ShowWindow(hwnd, SW_RESTORE)
    _force_foreground(hwnd)


def close(hwnd: int) -> None:
    _require_win()
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def work_area() -> tuple[int, int, int, int]:
    """Monitor work area (left, top, right, bottom) excluding taskbar."""
    _require_win()
    rect = wintypes.RECT()
    if not user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        # Fallback: full primary screen
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        return 0, 0, w, h
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def snap_half(hwnd: int, side: str) -> None:
    """Snap *hwnd* to the left or right half of the work area (Aero-snap style)."""
    _require_win()
    side = (side or "").strip().lower()
    if side not in ("left", "right"):
        raise WindowError("Snap side must be left or right.")
    left, top, right, bottom = work_area()
    width = right - left
    height = bottom - top
    half = width // 2
    x = left if side == "left" else left + half
    # Restore first so maximized windows can be resized.
    user32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.05)
    user32.SetWindowPos(
        hwnd,
        HWND_TOP,
        x,
        top,
        half,
        height,
        SWP_SHOWWINDOW,
    )
    _force_foreground(hwnd)


def send_key(hwnd: int, vk: int, *, repeats: int = 1) -> None:
    """Focus *hwnd* and synthesize key press(es)."""
    _require_win()
    _force_foreground(hwnd)
    time.sleep(0.12)
    for _ in range(max(1, repeats)):
        # Post to the window *and* inject global keybd so VLC sees it.
        user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
        user32.PostMessageW(hwnd, WM_KEYUP, vk, 0xC0000001)
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.08)


def wait_for_window(
    *,
    process: str | None = None,
    title_substr: str | None = None,
    timeout_s: float = 8.0,
    poll_s: float = 0.25,
) -> WindowInfo | None:
    """Poll until a matching window appears or *timeout_s* elapses."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        hits = find_windows(process=process, title_substr=title_substr)
        if hits:
            titled = [h for h in hits if h.title and h.title.lower() not in (process or "",)]
            return (titled or hits)[0]
        time.sleep(poll_s)
    return None


PLAYER_PROCESSES: tuple[str, ...] = (
    "vlc",
    "mpc-hc64",
    "mpc-hc",
    "mpc-be64",
    "mpc-be",
    "wmplayer",
    "movies",
    "potplayer",
    "potplayermini64",
)


def find_vlc_exe() -> Path | None:
    """Locate vlc.exe on this machine (PATH + common install dirs)."""
    which = shutil.which("vlc") or shutil.which("vlc.exe")
    if which:
        return Path(which)
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "VideoLAN" / "VLC" / "vlc.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "VideoLAN"
        / "VLC"
        / "vlc.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "VideoLAN" / "VLC" / "vlc.exe",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def open_in_vlc(path: Path, *, fullscreen: bool = False) -> subprocess.Popen[bytes] | None:
    """Launch *path* in VLC. Uses ``--fullscreen`` for true video fullscreen.

    Returns the Popen handle, or None if VLC is not installed (caller should
    fall back to os.startfile).
    """
    vlc = find_vlc_exe()
    if vlc is None:
        return None
    args = [str(vlc), "--no-video-title-show", str(path)]
    if fullscreen:
        # True VLC video fullscreen (no title bar / playlist / controls chrome).
        args.insert(1, "--fullscreen")
    # DETACHED so JARVIS exit doesn't kill the player mid-watch.
    creation = 0
    if sys.platform == "win32":
        creation = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    return subprocess.Popen(
        args,
        close_fds=True,
        creationflags=creation,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def fullscreen_media_player(
    *,
    prefer: tuple[str, ...] = PLAYER_PROCESSES,
    timeout_s: float = 10.0,
) -> WindowInfo:
    """Enter *video* fullscreen on a media player (VLC ``f``, not maximize).

    Raises WindowError if no player window shows up in time.
    """
    _require_win()
    deadline = time.monotonic() + timeout_s
    win: WindowInfo | None = None
    while time.monotonic() < deadline:
        for proc in prefer:
            hits = find_windows(process=proc)
            if hits:
                titled = [h for h in hits if h.title and h.title.lower() != proc]
                # Prefer a window whose title looks like media (has a dot/extension hint
                # or is longer than the process name).
                win = (titled or hits)[0]
                break
        if win is not None:
            break
        time.sleep(0.25)
    if win is None:
        raise WindowError("I couldn't find a media player window to fullscreen.")

    _force_foreground(win.hwnd)
    time.sleep(0.25)
    # VLC: 'f' = video fullscreen (double-click equivalent). Send twice is safe
    # only if we aren't already fullscreen — VLC toggles; prefer single with
    # a short settle then one more if still has a normal frame... keep single.
    if win.process == "vlc":
        send_key(win.hwnd, VK_F, repeats=1)
        time.sleep(0.35)
        # Second press only if window still looks windowed (has sizable non-fullscreen).
        # Hard to detect reliably; one press is the VLC default for enter fullscreen.
    else:
        send_key(win.hwnd, VK_F11, repeats=1)
    return win


def snap_media_player(
    side: str,
    *,
    prefer: tuple[str, ...] = PLAYER_PROCESSES,
    timeout_s: float = 10.0,
) -> WindowInfo:
    """Wait for a media player and snap it to the left/right half of the screen."""
    _require_win()
    deadline = time.monotonic() + timeout_s
    win: WindowInfo | None = None
    while time.monotonic() < deadline:
        for proc in prefer:
            hits = find_windows(process=proc)
            if hits:
                titled = [h for h in hits if h.title and h.title.lower() != proc]
                win = (titled or hits)[0]
                break
        if win is not None:
            break
        time.sleep(0.25)
    if win is None:
        raise WindowError("I couldn't find a media player window to snap.")
    snap_half(win.hwnd, side)
    return win
