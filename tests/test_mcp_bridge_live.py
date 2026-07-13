"""Opt-in end-to-end test against the REAL Claude CLI + live MCP tool bridge.

Excluded from the default suite (marker ``claude_live`` is deselected in
pyproject) because it invokes the real ``claude`` binary and BURNS Claude usage.
Handlers are fakes, so no real OS side effects occur.

Run it deliberately::

    py -3.13 -m pytest tests/test_mcp_bridge_live.py -m claude_live -v

It proves the Claude CLI can discover and call JARVIS's tools over the
in-process HTTP MCP server: we ask Claude to skip the track and assert the fake
Spotify player recorded a ``next`` call (i.e. the tool actually fired) and a
spotify step reached the bus.
"""

from __future__ import annotations

import shutil

import pytest

from jarvis.brain.claude_code import ClaudeCodeBrain
from jarvis.brain.mcp_bridge import JarvisToolBridge
from jarvis.config import JarvisConfig
from jarvis.events import EventBus, StepStarted
from jarvis.spotify.fake import FakeSpotifyPlayer, sample_spotify

pytestmark = pytest.mark.claude_live


@pytest.fixture(scope="module")
def claude_available() -> None:
    if not shutil.which("claude"):
        pytest.skip("claude CLI not on PATH")


def test_real_cli_calls_spotify_tool(claude_available) -> None:
    bus = EventBus()
    steps: list[object] = []
    bus.subscribe(steps.append)

    player = FakeSpotifyPlayer()
    bridge = JarvisToolBridge(bus=bus, spotify=sample_spotify(player=player))

    brain = ClaudeCodeBrain(
        config=JarvisConfig(claude_model="haiku", speak=False),
        bus=bus,
        tool_bridge=bridge,
    )
    try:
        turn = brain.ask(
            "Use your JARVIS spotify tool to skip to the next track. "
            "Call the tool; do not answer without calling it."
        )
        assert turn.reply
        assert "next" in player.calls, (
            "the Claude CLI did not reach the spotify MCP tool "
            f"(player.calls={player.calls!r})"
        )
        assert any(
            isinstance(e, StepStarted) and e.name == "spotify" for e in steps
        )
    finally:
        bridge.stop()
