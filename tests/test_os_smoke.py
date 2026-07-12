"""Opt-in real-OS smoke tests (issue 13): ``pytest -m os_smoke``.

Deselected automatically in the default run (see addopts in pyproject.toml).
These really launch Notepad, drive its window through the Win32 layer
(snap / minimize / restore), and open a media file with the real player —
then clean up (windows closed, no orphan processes). Expect brief flashes of
Notepad / VLC on screen while they run.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.os_smoke,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows-only"),
]


def _user32():
    return ctypes.windll.user32  # type: ignore[attr-defined]


def _is_iconic(hwnd: int) -> bool:
    return bool(_user32().IsIconic(hwnd))


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    from ctypes import wintypes

    rect = wintypes.RECT()
    _user32().GetWindowRect(hwnd, ctypes.byref(rect))
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _hwnds(process: str) -> set[int]:
    from jarvis.windows.win32api import find_windows

    return {w.hwnd for w in find_windows(process=process)}


def _wait_until(predicate, timeout_s: float = 10.0, poll_s: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return bool(predicate())


def _pid_of(hwnd: int, process: str) -> int | None:
    from jarvis.windows.win32api import find_windows

    for w in find_windows(process=process):
        if w.hwnd == hwnd:
            return w.pid
    return None


def _pids(process: str) -> set[int]:
    from jarvis.windows.win32api import find_windows

    return {w.pid for w in find_windows(process=process)}


def _force_kill(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        timeout=10,
        check=False,
    )


def test_notepad_launch_snap_minimize_restore_close() -> None:
    """Launch Notepad for real, snap/minimize/restore via win32api, close it.

    Safe alongside a user's existing Notepad: we only ever drive the NEW
    window our launch created, and never taskkill a process that also hosts
    pre-existing windows (Win11 Notepad shares one process across windows).
    """
    from jarvis.apps.handler import build_app_handler
    from jarvis.windows.win32api import close, minimize, restore, snap_half, work_area

    before = _hwnds("notepad")
    pids_before = _pids("notepad")

    handler = build_app_handler()
    hwnd: int | None = None
    try:
        # Force a new instance/window even if Notepad is already running.
        result = handler.try_handle("open a new notepad window")
        assert result is not None and result.ok, result
        assert any(a.name == "app_launch" for a in result.actions), result.actions

        if not _wait_until(lambda: _hwnds("notepad") - before, 15.0):
            if before:
                pytest.skip(
                    "Win11 Notepad merged the launch into the existing window "
                    "as a tab (no new window to own) — close Notepad and rerun."
                )
            pytest.fail("Notepad window never appeared")
        hwnd = (_hwnds("notepad") - before).pop()

        # Snap to the left half (Aero-snap style via SetWindowPos).
        snap_half(hwnd, "left")
        time.sleep(0.4)
        wa_left, wa_top, wa_right, _wa_bottom = work_area()
        left, _top, right, _bottom = _window_rect(hwnd)
        width = right - left
        wa_width = wa_right - wa_left
        assert abs(left - wa_left) <= 50, f"window left={left}, work-area left={wa_left}"
        assert 0.35 * wa_width <= width <= 0.65 * wa_width, (
            f"snapped width {width} is not ~half of work area {wa_width}"
        )

        minimize(hwnd)
        assert _wait_until(lambda: _is_iconic(hwnd), 5.0), "window did not minimize"

        restore(hwnd)
        assert _wait_until(lambda: not _is_iconic(hwnd), 5.0), "window did not restore"

        close(hwnd)
        assert _wait_until(lambda: hwnd not in _hwnds("notepad"), 10.0), (
            "Notepad window did not close"
        )
        hwnd = None
    finally:
        # Never leave an orphan window/process behind — but never kill a
        # process that also hosts the user's pre-existing Notepad windows.
        if hwnd is not None and hwnd in _hwnds("notepad"):
            pid = _pid_of(hwnd, "notepad")
            close(hwnd)
            still_open = not _wait_until(lambda: hwnd not in _hwnds("notepad"), 5.0)
            if still_open and pid and pid not in pids_before:
                _force_kill(pid)


def _write_silent_wav(path: Path, seconds: float = 1.0) -> None:
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(8000)
        fh.writeframes(b"\x00\x00" * int(8000 * seconds))


def test_media_open_for_real_then_close(tmp_path: Path) -> None:
    """Open a media file through the real media slice, then close the player."""
    from jarvis.media.handler import LocalMediaHandler
    from jarvis.windows.win32api import PLAYER_PROCESSES, close, find_windows

    stem = f"jarvis os smoke {os.getpid()}"
    media_file = tmp_path / f"{stem}.wav"
    _write_silent_wav(media_file)

    players_before = {p: _hwnds(p) for p in PLAYER_PROCESSES}

    handler = LocalMediaHandler(roots=(tmp_path,))
    new_hwnd: int | None = None
    new_proc: str | None = None
    try:
        result = handler.try_handle(f"play {stem} from downloads")
        assert result is not None and result.ok, result
        opened = [a for a in result.actions if a.name == "local_media_open"]
        assert opened and str(media_file) in opened[0].detail, result.actions

        def _find_new_player():
            nonlocal new_hwnd, new_proc
            for proc in PLAYER_PROCESSES:
                fresh = _hwnds(proc) - players_before[proc]
                if fresh:
                    new_hwnd, new_proc = fresh.pop(), proc
                    return True
            # Default-app fallback: window titled after the file.
            for w in find_windows(title_substr=stem):
                new_hwnd, new_proc = w.hwnd, w.process
                return True
            return False

        assert _wait_until(_find_new_player, 20.0), (
            "no media player window appeared after opening the file"
        )
        assert new_hwnd is not None

        close(new_hwnd)
        probe = new_proc if new_proc in PLAYER_PROCESSES else None
        if probe:
            assert _wait_until(
                lambda: new_hwnd not in _hwnds(probe), 10.0
            ), "player window did not close"
        new_hwnd = None
    finally:
        if new_hwnd is not None:
            pid = _pid_of(new_hwnd, new_proc or "")
            close(new_hwnd)
            time.sleep(1.0)
            if pid and new_proc and new_hwnd in _hwnds(new_proc):
                _force_kill(pid)
