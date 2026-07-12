"""Window management intents + handler (Win32 ops injected — no real UI)."""

from __future__ import annotations

from jarvis.brain.fake import FakeBrain
from jarvis.core import handle_command
from jarvis.tts.fake import FakeSpeaker
from jarvis.windows.handler import WindowHandler
from jarvis.windows.intents import WindowIntentKind, classify
from jarvis.windows.win32api import WindowInfo


def test_classify_fullscreen_vlc() -> None:
    i = classify("fullscreen vlc")
    assert i.kind is WindowIntentKind.FULLSCREEN
    assert "vlc" in i.target.lower()


def test_classify_minimize_chrome() -> None:
    i = classify("minimize chrome")
    assert i.kind is WindowIntentKind.MINIMIZE
    assert "chrome" in i.target.lower()


def test_classify_does_not_steal_play_from_downloads() -> None:
    i = classify("play Project Hail Mary from downloads fullscreen")
    assert i.kind is WindowIntentKind.UNRELATED


def test_classify_snap_left() -> None:
    i = classify("snap vlc to the left half")
    assert i.kind is WindowIntentKind.SNAP
    assert i.snap == "left"
    assert "vlc" in i.target.lower()


def test_classify_minimize_all() -> None:
    i = classify("minimize all windows")
    assert i.kind is WindowIntentKind.MINIMIZE_ALL


def test_handler_minimize_all() -> None:
    calls: list[str] = []
    h = WindowHandler(ops={"minimize_all": lambda: calls.append("all") or 3})
    r = h.try_handle("minimize all windows")
    assert r is not None and r.ok
    assert calls == ["all"]
    assert "3" in r.reply


def test_handler_fullscreen_bare_uses_media_player() -> None:
    fake_win = WindowInfo(hwnd=1, title="Movie", pid=9, process="vlc")
    calls: list[str] = []

    def fs(**_kw):
        calls.append("fs")
        return fake_win

    h = WindowHandler(ops={"fullscreen_media_player": fs})
    r = h.try_handle("go fullscreen")
    assert r is not None
    assert r.ok
    assert calls == ["fs"]
    assert any(a.name == "window_fullscreen" for a in r.actions)


def test_handler_focus_resolves_alias() -> None:
    fake_win = WindowInfo(hwnd=42, title="VLC media player", pid=1, process="vlc")
    focused: list[int] = []

    h = WindowHandler(
        ops={
            "find_windows": lambda **kw: [fake_win]
            if kw.get("process") == "vlc"
            else [],
            "focus": focused.append,
            "wait_for_window": lambda **kw: None,
        }
    )
    r = h.try_handle("focus vlc")
    assert r is not None and r.ok
    assert focused == [42]


def test_handle_command_routes_window_intent() -> None:
    fake_win = WindowInfo(hwnd=7, title="Spotify", pid=2, process="spotify")
    h = WindowHandler(
        ops={
            "find_windows": lambda **kw: [fake_win]
            if "spotify" in (kw.get("process") or "")
            or "spotify" in (kw.get("title_substr") or "")
            else [],
            "minimize": lambda hwnd: None,
            "wait_for_window": lambda **kw: None,
        }
    )
    result = handle_command(
        "minimize spotify",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        windows=h,
    )
    assert result.ok
    assert any(a.name == "window_minimize" for a in result.actions)
