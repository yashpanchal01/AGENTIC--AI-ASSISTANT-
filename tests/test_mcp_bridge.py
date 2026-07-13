"""Unit tests for the MCP tool bridge (issue 15).

Covers tool schemas, dispatch into FAKE handlers, error → StepFailed mapping,
and — the safety-critical part — that every side-effecting tool call passes the
SAME jarvis.confirm gate as a voice command: secrets are hard-denied and never
execute, risky calls need confirmation, and declined calls never reach the
handler. No network, no Claude, no real OS.
"""

from __future__ import annotations

from types import SimpleNamespace

from jarvis.apps.handler import AppHandler
from jarvis.brain.mcp_bridge import (
    CANCELLED_REPLY,
    SECRET_REFUSAL,
    TOOL_NAMES,
    JarvisToolBridge,
    allowed_tool_ids,
    tool_definitions,
)
from jarvis.confirm import FixedConfirmer
from jarvis.events import EventBus, StepFailed, StepFinished, StepStarted
from jarvis.google.fake import sample_workspace
from jarvis.memory.handler import MemoryHandlerImpl
from jarvis.memory.store import MemoryStore
from jarvis.spotify.fake import FakeSpotifyPlayer, sample_spotify
from jarvis.windows.handler import WindowHandler


def _bus_with_log() -> tuple[EventBus, list[object]]:
    bus = EventBus()
    events: list[object] = []
    bus.subscribe(events.append)
    return bus, events


def _fake_apps(launches: list[str]) -> AppHandler:
    # Stateful fake: a matching window appears only AFTER launch, so honest-
    # outcome verification passes without a real Win32 window list.
    def _find(**kw):
        proc = str(kw.get("process") or "").lower()
        if proc and any(proc == k or proc in k or k in proc for k in launches):
            return [SimpleNamespace(hwnd=1, title=proc, process=proc)]
        return []

    return AppHandler(
        ops={
            "find_windows": _find,
            "focus": lambda hwnd: None,
            "launch": lambda spec, force_new=False: launches.append(spec.key),
        },
        verify_poll_s=0.0,
    )


def _fake_windows(close_calls: list[int]) -> WindowHandler:
    win = SimpleNamespace(hwnd=1234, title="Chrome", process="chrome")
    return WindowHandler(
        ops={
            "find_windows": lambda **kw: [win],
            "wait_for_window": lambda **kw: None,
            "close": lambda hwnd: close_calls.append(int(hwnd)),
            "focus": lambda hwnd: None,
            "minimize": lambda hwnd: None,
            "maximize": lambda hwnd: None,
            "restore": lambda hwnd: None,
            "snap_half": lambda hwnd, side: None,
        }
    )


# --- tool catalogue ---------------------------------------------------------


def test_tool_definitions_expose_the_domains() -> None:
    defs = tool_definitions()
    names = [d["name"] for d in defs]
    assert names == list(TOOL_NAMES)
    assert set(names) == {
        "spotify",
        "apps",
        "windows",
        "media",
        "system",
        "memory",
        "google_read",
    }
    for d in defs:
        schema = d["inputSchema"]
        assert schema["type"] == "object"
        assert "command" in schema["properties"]
        assert schema["required"] == ["command"]
        assert d["description"]


def test_allowed_tool_ids_are_namespaced() -> None:
    assert allowed_tool_ids() == [f"mcp__jarvis__{n}" for n in TOOL_NAMES]


# --- dispatch into fakes ----------------------------------------------------


def test_dispatch_spotify_next_fires_handler_and_bus() -> None:
    bus, events = _bus_with_log()
    player = FakeSpotifyPlayer()
    bridge = JarvisToolBridge(bus=bus, spotify=sample_spotify(player=player))

    res = bridge.call_tool("spotify", {"command": "play the next track"})

    assert res.is_error is False
    assert res.text == "Skipped."
    assert "next" in player.calls
    assert [type(e) for e in events] == [StepStarted, StepFinished]
    assert events[0].name == "spotify" and events[1].name == "spotify"


def test_dispatch_apps_open_launches_and_bus_orders_start_finish() -> None:
    bus, events = _bus_with_log()
    launches: list[str] = []
    bridge = JarvisToolBridge(bus=bus, apps=_fake_apps(launches))

    res = bridge.call_tool("apps", {"command": "open spotify"})

    assert res.is_error is False
    assert "Spotify" in res.text
    assert launches == ["spotify"]
    assert isinstance(events[0], StepStarted)
    assert isinstance(events[1], StepFinished)


def test_unknown_tool_is_reported_not_crashed() -> None:
    bridge = JarvisToolBridge(bus=EventBus())
    # Via JSON-RPC: an unknown tool name is an isError result, not a crash.
    resp = bridge.handle_jsonrpc(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "nope", "arguments": {"command": "x"}}}
    )
    assert resp["result"]["isError"] is True


def test_missing_handler_maps_to_step_failed() -> None:
    bus, events = _bus_with_log()
    # No spotify handler wired → the tool is unavailable, not a silent no-op.
    bridge = JarvisToolBridge(bus=bus, spotify=None)
    res = bridge.call_tool("spotify", {"command": "pause the music"})
    assert res.is_error is True
    assert res.error == "unavailable"
    assert isinstance(events[-1], StepFailed)


def test_handler_exception_maps_to_step_failed() -> None:
    class Boom:
        def try_handle(self, _utterance):
            raise RuntimeError("kaboom")

    bus, events = _bus_with_log()
    bridge = JarvisToolBridge(bus=bus, spotify=Boom())

    res = bridge.call_tool("spotify", {"command": "pause the music"})

    assert res.is_error is True
    assert res.error == "RuntimeError"
    assert isinstance(events[-1], StepFailed)
    assert events[-1].error == "RuntimeError"


def test_dispatch_system_brightness_not_confirm_gated() -> None:
    """The system tool (issue 16) runs without a confirm prompt (non-destructive)."""
    from jarvis.system.handler import SystemHandler

    bus, events = _bus_with_log()
    calls: list[int] = []
    # A confirmer that would fail the test if the gate ever consulted it.
    confirmer = FixedConfirmer(answer=False)
    system = SystemHandler(
        capture_roots=(), set_brightness=calls.append, open_fn=lambda p: None
    )
    bridge = JarvisToolBridge(bus=bus, confirmer=confirmer, system=system)

    res = bridge.call_tool("system", {"command": "set brightness to 50"})

    assert res.is_error is False  # would be cancelled if gated with answer=False
    assert calls == [50]
    assert [type(e) for e in events] == [StepStarted, StepFinished]
    assert events[0].name == "system"


def test_google_write_is_refused_read_only() -> None:
    bus, events = _bus_with_log()
    bridge = JarvisToolBridge(bus=bus, google=sample_workspace())

    res = bridge.call_tool("google_read", {"command": "reply to the latest email"})

    assert res.is_error is True
    assert res.denied is True
    assert "read-only" in res.text.lower()
    assert isinstance(events[-1], StepFailed)


def test_google_read_summarizes_calendar() -> None:
    bridge = JarvisToolBridge(bus=EventBus(), google=sample_workspace())
    res = bridge.call_tool("google_read", {"command": "what's on my calendar today"})
    assert res.is_error is False
    assert "Standup" in res.text


# --- confirm gate (safety-critical) -----------------------------------------


def test_secret_request_is_hard_denied_and_never_executes(tmp_path) -> None:
    bus, events = _bus_with_log()
    store = MemoryStore(tmp_path / "mem")
    bridge = JarvisToolBridge(
        bus=bus,
        confirmer=FixedConfirmer(answer=True),  # even a yes must not save a secret
        memory=MemoryHandlerImpl(store=store),
    )

    res = bridge.call_tool(
        "memory", {"command": "remember that my banking password is hunter2"}
    )

    assert res.denied is True
    assert res.text == SECRET_REFUSAL
    # Never written — the handler was not reached.
    assert store.notes() == []
    # StepFailed(secret_denied), and NO StepFinished.
    assert any(isinstance(e, StepFailed) and e.error == "secret_denied" for e in events)
    assert not any(isinstance(e, StepFinished) for e in events)


def test_risky_request_declined_never_reaches_handler() -> None:
    bus, events = _bus_with_log()
    launches: list[str] = []
    confirmer = FixedConfirmer(answer=False)
    bridge = JarvisToolBridge(bus=bus, confirmer=confirmer, apps=_fake_apps(launches))

    # "delete" is a jarvis.confirm risky verb — the gate must ask first.
    res = bridge.call_tool("apps", {"command": "delete the chrome shortcut"})

    assert res.text == CANCELLED_REPLY
    assert res.is_error is True
    assert confirmer.calls, "confirmer was not consulted for a risky call"
    assert launches == [], "handler ran despite a declined confirmation"
    assert any(
        isinstance(e, StepFailed) and e.error == "confirmation_declined" for e in events
    )


def test_close_window_requires_confirmation() -> None:
    # "close" is not in jarvis.confirm's generic list; the bridge tightens it.
    bus, events = _bus_with_log()
    close_calls: list[int] = []
    confirmer = FixedConfirmer(answer=False)
    bridge = JarvisToolBridge(
        bus=bus, confirmer=confirmer, windows=_fake_windows(close_calls)
    )

    res = bridge.call_tool("windows", {"command": "close chrome"})

    assert res.text == CANCELLED_REPLY
    assert confirmer.calls, "close was not gated by ask-first"
    assert close_calls == [], "window was closed without confirmation"


def test_no_confirmer_declines_risky_by_default() -> None:
    launches: list[str] = []
    bridge = JarvisToolBridge(confirmer=None, apps=_fake_apps(launches))
    res = bridge.call_tool("apps", {"command": "delete the chrome shortcut"})
    assert res.text == CANCELLED_REPLY
    assert launches == []


def test_confirmed_forget_proceeds(tmp_path) -> None:
    store = MemoryStore(tmp_path / "mem")
    store.remember("my old address is 5 Foo Street")
    assert store.notes()

    confirmer = FixedConfirmer(answer=True)
    bridge = JarvisToolBridge(
        bus=EventBus(), confirmer=confirmer, memory=MemoryHandlerImpl(store=store)
    )

    res = bridge.call_tool("memory", {"command": "forget my old address"})

    assert confirmer.calls, "forget should be gated"
    assert res.is_error is False
    assert store.notes() == [], "confirmed forget did not run"
