"""Pytest isolation for JARVIS home, settings, audit log, and the real OS.

Redirects ``JARVIS_HOME`` to a temp directory so unit tests never read the
developer's ``~/.jarvis/settings.json`` or append to the real audit log.
Also sets ``JARVIS_AUDIT=0`` as a belt-and-suspenders disable for any code
path that still constructs a default audit logger.

Hermetic OS adapters (issue 13): CLI-driven tests (``jarvis.cli.main``) get
injected fake apps/windows/media handlers so the default suite can never
focus a running Spotify, launch a real Notepad, or scan the developer's
Downloads for media. Real-OS coverage is opt-in via ``pytest -m os_smoke``;
tests carrying that marker skip the fakes.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_jarvis_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("jarvis_home")
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.setenv("JARVIS_AUDIT", "0")
    # Clear explicit settings override if a developer shell exported one.
    monkeypatch.delenv("JARVIS_SETTINGS", raising=False)
    yield home


@pytest.fixture(autouse=True)
def _hermetic_os_adapters(request, monkeypatch):
    """Keep the default suite off the real Win32 / app-launch / media surfaces."""
    if "os_smoke" in request.keywords:
        yield
        return

    from jarvis import cli as jarvis_cli
    from jarvis.apps.handler import AppHandler
    from jarvis.media.handler import LocalMediaHandler
    from jarvis.system.handler import SystemHandler
    from jarvis.windows.handler import WindowHandler
    from jarvis.windows.win32api import WindowError

    def _no_player(*_args, **_kwargs):
        raise WindowError("I couldn't find a media player window.")

    monkeypatch.setattr(
        jarvis_cli,
        "make_apps",
        lambda: AppHandler(
            ops={
                "find_windows": lambda **kw: [],
                "focus": lambda hwnd: None,
                "launch": lambda spec, force_new=False: None,
            }
        ),
    )
    monkeypatch.setattr(
        jarvis_cli,
        "make_windows",
        lambda: WindowHandler(
            ops={
                "find_windows": lambda **kw: [],
                "wait_for_window": lambda **kw: None,
                "minimize_all": lambda: 0,
                "fullscreen_media_player": _no_player,
                "snap_media_player": _no_player,
                "focus": lambda hwnd: None,
                "minimize": lambda hwnd: None,
                "maximize": lambda hwnd: None,
                "restore": lambda hwnd: None,
                "close": lambda hwnd: None,
                "snap_half": lambda hwnd, side: None,
            }
        ),
    )
    monkeypatch.setattr(
        jarvis_cli,
        "make_media",
        lambda config: LocalMediaHandler(roots=()),
    )
    monkeypatch.setattr(
        jarvis_cli,
        "make_system",
        lambda config: SystemHandler(
            capture_roots=(),
            get_brightness=lambda: 50,
            set_brightness=lambda level: None,
            open_fn=lambda path: None,
        ),
    )
    yield
