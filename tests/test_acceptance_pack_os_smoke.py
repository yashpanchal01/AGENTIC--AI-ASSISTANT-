"""Real-OS acceptance variants for the canonical tasks (issue 17).

Opt-in only: ``pytest -m os_smoke`` (deselected in the default run). These drive
the SHIPPED handlers against the real display / disk / Win32 for tasks (a), (c)
and (d), then clean up. Expect brief flashes of a player / Notepad and a short
brightness dip while they run.

Safety notes (why these are shaped the way they are):
* (c) A faithful "close all the windows" reflex calls a GLOBAL minimize-all,
  which would minimize the user's whole desktop — too disruptive to run here.
  Instead we drive the real idiom + handler but inject a minimize-all op scoped
  to a single Notepad window we spawned, and assert THAT window minimizes and
  its process is NOT closed. The global routing is covered by the fakes suite.
* (d) The canonical utterance sets brightness to 0. We capture the original
  first and ALWAYS restore it in ``finally`` (like issue 16), so the screen is
  never left dark. Skips (not fails) on a panel without WMI brightness.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
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


def _hwnds(process: str) -> set[int]:
    from jarvis.windows.win32api import find_windows

    return {w.hwnd for w in find_windows(process=process)}


def _pids(process: str) -> set[int]:
    from jarvis.windows.win32api import find_windows

    return {w.pid for w in find_windows(process=process)}


def _pid_of(hwnd: int, process: str) -> int | None:
    from jarvis.windows.win32api import find_windows

    for w in find_windows(process=process):
        if w.hwnd == hwnd:
            return w.pid
    return None


def _force_kill(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        timeout=10,
        check=False,
    )


def _wait_until(predicate, timeout_s: float = 10.0, poll_s: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return bool(predicate())


# ==========================================================================
# (a) "open the screen recording we just captured" — real open, then close
# ==========================================================================


def test_a_open_latest_capture_for_real(tmp_path: Path) -> None:
    """Canonical phrasing opens the newest file in a TEMP capture folder."""
    import os
    import wave

    from jarvis.system.handler import SystemHandler
    from jarvis.windows.win32api import PLAYER_PROCESSES, close, find_windows

    stem = f"jarvis acceptance capture {os.getpid()}"
    older = tmp_path / f"{stem} old.mp4"
    newest = tmp_path / f"{stem} new.mp4"

    def _silent_wav(path: Path) -> None:
        with wave.open(str(path), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(8000)
            fh.writeframes(b"\x00\x00" * 8000)

    _silent_wav(older)
    time.sleep(1.1)
    _silent_wav(newest)

    players_before = {p: _hwnds(p) for p in PLAYER_PROCESSES}
    handler = SystemHandler(capture_roots=(tmp_path,))
    new_hwnd: int | None = None
    new_proc: str | None = None
    try:
        result = handler.try_handle("open the screen recording we just captured")
        assert result is not None and result.ok, result
        opened = [a for a in result.actions if a.name == "latest_capture_open"]
        assert opened and str(newest) in opened[0].detail, result.actions

        def _find_new_player() -> bool:
            nonlocal new_hwnd, new_proc
            for proc in PLAYER_PROCESSES:
                fresh = _hwnds(proc) - players_before[proc]
                if fresh:
                    new_hwnd, new_proc = fresh.pop(), proc
                    return True
            for w in find_windows(title_substr=stem):
                new_hwnd, new_proc = w.hwnd, w.process
                return True
            return False

        assert _wait_until(_find_new_player, 20.0), "no player window appeared"
        assert new_hwnd is not None
        close(new_hwnd)
        new_hwnd = None
    finally:
        if new_hwnd is not None:
            pid = _pid_of(new_hwnd, new_proc or "")
            close(new_hwnd)
            time.sleep(1.0)
            if pid and new_proc and new_hwnd in _hwnds(new_proc):
                _force_kill(pid)


# ==========================================================================
# (c) "close all the windows" — MINIMIZE (scoped to our own window), never close
# ==========================================================================


def test_c_close_all_minimizes_not_closes_scoped(tmp_path: Path) -> None:
    """Real idiom + handler; minimize-all scoped to a Notepad WE spawned.

    Faithful to (c)'s invariant (minimize, never close) on a real window,
    without minimizing the user's whole desktop. The window must end iconic and
    its process must survive.
    """
    from jarvis.apps.handler import build_app_handler
    from jarvis.windows.handler import WindowHandler
    from jarvis.windows.win32api import close, minimize, restore

    before = _hwnds("notepad")
    pids_before = _pids("notepad")

    apps = build_app_handler()
    hwnd: int | None = None
    try:
        launched = apps.try_handle("open a new notepad window")
        assert launched is not None and launched.ok, launched

        if not _wait_until(lambda: _hwnds("notepad") - before, 15.0):
            if before:
                pytest.skip("Win11 merged Notepad into an existing window as a tab")
            pytest.fail("Notepad window never appeared")
        hwnd = (_hwnds("notepad") - before).pop()
        owned = hwnd

        # Scope the reflex's minimize-all to just our window (never the desktop).
        minimized: list[int] = []

        def _scoped_minimize_all() -> int:
            minimize(owned)
            minimized.append(owned)
            return 1

        handler = WindowHandler(ops={"minimize_all": _scoped_minimize_all})
        result = handler.try_handle("close all the windows")

        assert result is not None and result.ok, result
        assert any(a.name == "window_minimize_all" for a in result.actions)
        assert minimized == [owned], "minimize-all did not run for our window"
        assert _wait_until(lambda: _is_iconic(owned), 5.0), "window did not minimize"
        # The idiom MINIMIZES — the process must still be alive (nothing closed).
        assert owned in {
            w for w in _hwnds("notepad")
        }, "window disappeared — it was closed, not minimized"

        restore(owned)
        _wait_until(lambda: not _is_iconic(owned), 5.0)
        close(owned)
        _wait_until(lambda: owned not in _hwnds("notepad"), 10.0)
        hwnd = None
    finally:
        if hwnd is not None and hwnd in _hwnds("notepad"):
            pid = _pid_of(hwnd, "notepad")
            restore(hwnd)
            close(hwnd)
            still = not _wait_until(lambda: hwnd not in _hwnds("notepad"), 5.0)
            if still and pid and pid not in pids_before:
                _force_kill(pid)


# ==========================================================================
# (d) "dim my brightness to zero" — real WMI set, then RESTORE the original
# ==========================================================================


def test_d_dim_brightness_to_zero_for_real_then_restore() -> None:
    from jarvis.system.brightness import (
        BrightnessError,
        default_get_brightness,
    )
    from jarvis.system.handler import SystemHandler

    try:
        original = default_get_brightness()
    except BrightnessError as exc:
        pytest.skip(f"WMI brightness unsupported on this device: {exc}")

    handler = SystemHandler(capture_roots=())  # real WMI get/set defaults
    try:
        result = handler.try_handle("dim my brightness to zero")
        assert result is not None and result.ok, result
        assert any(
            a.name == "brightness_set" and a.detail == "0" for a in result.actions
        )
        time.sleep(0.4)
        got = default_get_brightness()
        assert got <= 10, f"brightness did not drop to ~0 (read {got})"
    finally:
        # ALWAYS restore — never leave the screen dark.
        from jarvis.system.brightness import default_set_brightness

        default_set_brightness(original)
