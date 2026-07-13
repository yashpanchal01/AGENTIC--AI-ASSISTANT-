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

    def _find(**kw):
        # No window before launch; a Brave window appears once launched.
        if launched and kw.get("process") == "brave":
            return [FakeWin(7)]
        return []

    h = AppHandler(
        ops={
            "find_windows": _find,
            "focus": lambda hwnd: None,
            "launch": lambda spec: launched.append(spec.key),
        },
        verify_poll_s=0.0,
    )
    r = h.try_handle("open brave")
    assert r is not None and r.ok
    assert launched == ["brave"]
    assert any(a.name == "app_launch" for a in r.actions)


def test_launch_but_no_window_reports_honest_failure() -> None:
    """Launch fired but no window ever came up → plain failure, not fake success."""
    launched: list[str] = []
    h = AppHandler(
        ops={
            "find_windows": lambda **kw: [],  # window never appears
            "focus": lambda hwnd: None,
            "launch": lambda spec: launched.append(spec.key),
        },
        verify_timeout_s=0.0,
        verify_poll_s=0.0,
    )
    r = h.try_handle("open brave")
    assert r is not None
    assert launched == ["brave"], "launch should still have been attempted"
    assert r.ok is False and r.error == "no_window"
    assert "nothing came up" in r.reply.lower()
    assert not any(a.name == "app_launch" for a in r.actions)


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


def test_resolve_chatgpt_opens_url_in_default_browser() -> None:
    """'chatgpt' resolves to a catalog entry that opens chatgpt.com once."""
    from jarvis.apps.catalog import resolve_app

    spec = resolve_app("chatgpt")
    assert spec is not None and spec.key == "chatgpt"
    assert spec.shell_start == "https://chatgpt.com"
    # No launch candidates → exactly one shell path, never two browsers/tabs.
    assert spec.launch_candidates == ()
    assert resolve_app("chat gpt").key == "chatgpt"


def test_open_chatgpt_launches_exactly_once() -> None:
    """Regression (live failure B): 'open chatgpt' triggers a single launch."""
    launched: list[str] = []
    h = AppHandler(
        ops={
            "find_windows": lambda **kw: [],
            "focus": lambda hwnd: None,
            "launch": lambda spec, force_new=False: launched.append(spec.key),
        },
        verify_poll_s=0.0,
    )
    r = h.try_handle("open chatgpt")
    assert r is not None and r.ok, r
    # Exactly one launch path — never the double-browser/double-tab bug.
    assert launched == ["chatgpt"]


def test_resolve_typo_fiels_explorer() -> None:
    """Regression (live failure B): typo'd 'fiels explorer' → file explorer."""
    from jarvis.apps.catalog import resolve_app

    assert resolve_app("fiels explorer").key == "explorer"
    assert resolve_app("file explorer").key == "explorer"
    assert resolve_app("notepat").key == "notepad"
    assert resolve_app("chrom").key == "chrome"
    assert resolve_app("firefix").key == "firefox"


def test_resolve_typo_never_crosses_distinct_apps() -> None:
    """Typo tolerance must not invent false positives between distinct apps."""
    from jarvis.apps.catalog import resolve_app

    assert resolve_app("brave").key == "brave"  # exact wins, stays brave
    # Nonsense / unknown names resolve to nothing (fall through to the brain).
    assert resolve_app("photoshop") is None
    assert resolve_app("xyzzy") is None
    assert resolve_app("do the thing") is None
    # Short names are matched exactly only — never fuzzed into a neighbour.
    assert resolve_app("vlc").key == "vlc"  # exact, not 'calc'
    assert resolve_app("clc") is None  # 3 chars → too short to fuzz to calc/vlc
    assert resolve_app("clac") is None  # 'calc' typo stays below the fuzz floor


def test_apps_defers_conversational_lead_to_brain() -> None:
    """A chatty request is not a terse command — apps reflex declines."""
    h = AppHandler(
        ops={
            "find_windows": lambda **kw: [],
            "focus": lambda hwnd: None,
            "launch": lambda spec, force_new=False: None,
        }
    )
    assert h.try_handle("can you open brave for me") is None
    assert h.try_handle("i wanna open chatgpt") is None
    # But a plain imperative still hits the reflex.
    assert h.try_handle("open brave") is not None


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
