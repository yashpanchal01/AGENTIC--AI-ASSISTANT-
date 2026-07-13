"""Real MCP handshake over the in-process HTTP server (issue 15).

Speaks correct MCP JSON-RPC to the bridge's Streamable-HTTP endpoint with an
ordinary urllib client (no Claude, no network egress — 127.0.0.1 only):
initialize → tools/list → tools/call. Proves the server the Claude CLI will
talk to actually implements MCP, and that a tools/call runs in-process through
the real handler + event bus.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from jarvis.brain.mcp_bridge import JarvisToolBridge
from jarvis.events import EventBus, StepFinished, StepStarted
from jarvis.spotify.fake import FakeSpotifyPlayer, sample_spotify


def _post(url: str, payload: dict) -> tuple[int, dict, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        raw = resp.read()
        data = json.loads(raw.decode("utf-8")) if raw else {}
        return resp.status, dict(resp.headers), data


@pytest.fixture()
def bridge() -> JarvisToolBridge:
    player = FakeSpotifyPlayer()
    b = JarvisToolBridge(bus=EventBus(), spotify=sample_spotify(player=player))
    b._player = player  # type: ignore[attr-defined]  # test handle
    b.ensure_started()
    try:
        yield b
    finally:
        b.stop()


def test_initialize_returns_capabilities_and_session(bridge: JarvisToolBridge) -> None:
    status, headers, data = _post(
        bridge.url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert status == 200
    result = data["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "jarvis"
    assert "tools" in result["capabilities"]
    assert headers.get("Mcp-Session-Id")


def test_initialized_notification_is_accepted(bridge: JarvisToolBridge) -> None:
    # A notification (no id) must not get a JSON-RPC response body.
    status, _headers, data = _post(
        bridge.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert status == 202
    assert data == {}


def test_tools_list_reports_six_tools(bridge: JarvisToolBridge) -> None:
    _status, _h, data = _post(
        bridge.url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    tools = data["result"]["tools"]
    assert {t["name"] for t in tools} == {
        "spotify",
        "apps",
        "windows",
        "media",
        "memory",
        "google_read",
    }


def test_tools_call_runs_in_process_through_handler_and_bus(
    bridge: JarvisToolBridge,
) -> None:
    seen: list[object] = []
    bridge.bus.subscribe(seen.append)

    _status, _h, data = _post(
        bridge.url,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "spotify", "arguments": {"command": "skip"}},
        },
    )

    result = data["result"]
    assert result["isError"] is False
    assert result["content"][0]["text"] == "Skipped."
    # The call executed the real (fake) handler in JARVIS's own process...
    assert "next" in bridge._player.calls  # type: ignore[attr-defined]
    # ...and emitted Start→Finish on the live bus.
    kinds = [type(e) for e in seen]
    assert StepStarted in kinds and StepFinished in kinds


def test_ping(bridge: JarvisToolBridge) -> None:
    _status, _h, data = _post(
        bridge.url, {"jsonrpc": "2.0", "id": 9, "method": "ping"}
    )
    assert data["result"] == {}
