"""Smart app open: focus if running, launch only if not."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.apps.handler import AppHandler
from jarvis.apps.intents import AppIntentKind, classify
from jarvis.brain.fake import FakeBrain
from jarvis.core import handle_command
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import BrainTurn


@dataclass
class FakeWin:
    hwnd: int
    title: str = "Brave"
    process: str = "brave"


def test_classify_open_brave() -> None:
    i = classify("open brave")
    assert i.kind is AppIntentKind.OPEN
    assert i.app.lower() == "brave"


def test_classify_open_new_window() -> None:
    for phrase in (
        "open a new brave window",
        "open new brave",
        "open new brave window",
    ):
        i = classify(phrase)
        assert i.kind is AppIntentKind.OPEN_NEW, phrase
        assert "brave" in i.app.lower(), phrase


def test_classify_leaves_media_alone() -> None:
    assert classify("play hail mary from downloads").kind is AppIntentKind.UNRELATED


def test_focus_existing_does_not_launch() -> None:
    launched: list[str] = []
    focused: list[int] = []
    h = AppHandler(
        ops={
            "find_windows": lambda **kw: [FakeWin(42)]
            if kw.get("process") == "brave"
            else [],
            "focus": focused.append,
            "launch": lambda spec: launched.append(spec.key),
        }
    )
    r = h.try_handle("open brave")
    assert r is not None and r.ok
    assert r.reply == "Focused Brave."
    assert focused == [42]
    assert launched == []
    assert any(a.name == "app_focus" for a in r.actions)


def test_launch_when_not_running() -> None:
    launched: list[str] = []
    h = AppHandler(
        ops={
            "find_windows": lambda **kw: [],
            "focus": lambda hwnd: None,
            "launch": lambda spec: launched.append(spec.key),
        }
    )
    r = h.try_handle("open brave")
    assert r is not None and r.ok
    assert launched == ["brave"]
    assert any(a.name == "app_launch" for a in r.actions)


def test_open_new_forces_launch() -> None:
    launched: list[tuple] = []
    h = AppHandler(
        ops={
            "find_windows": lambda **kw: [FakeWin(1)],
            "focus": lambda hwnd: None,
            "launch": lambda spec, force_new=False: launched.append((spec.key, force_new)),
        }
    )
    r = h.try_handle("open new brave")
    assert r is not None and r.ok
    assert launched == [("brave", True)]
    assert "new" in r.reply.lower()


def test_handle_command_routes_open_brave() -> None:
    focused: list[int] = []
    h = AppHandler(
        ops={
            "find_windows": lambda **kw: [FakeWin(9)]
            if kw.get("process") == "brave"
            else [],
            "focus": focused.append,
            "launch": lambda spec: (_ for _ in ()).throw(RuntimeError("no launch")),
        }
    )
    result = handle_command(
        "open brave",
        brain=FakeBrain(script=[BrainTurn(reply="brain should not run", actions=())]),
        speaker=FakeSpeaker(),
        apps=h,
    )
    assert result.reply == "Focused Brave."
    assert focused == [9]
