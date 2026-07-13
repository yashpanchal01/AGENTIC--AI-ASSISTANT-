"""End-to-end tool-bridge scenario (issue 15) — no Claude, no network.

The audit's problem 1: "open spotify and play the next track" used to fail
because the brain was banned from music. Here a FAKE brain (standing in for the
Claude CLI's tool-calling) issues the two tool calls through the bridge; we
assert apps.open then spotify.next both fire, the bus events are ordered
Start→Finish per call, and a spoken reply is produced through the real core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jarvis.brain.mcp_bridge import JarvisToolBridge
from jarvis.apps.handler import AppHandler
from jarvis.core import handle_command
from jarvis.events import EventBus, StepFinished, StepStarted
from jarvis.spotify.fake import FakeSpotifyPlayer, sample_spotify
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import BrainTurn


@dataclass
class ScriptedBridgeBrain:
    """Fake brain: on ask(), calls the JARVIS tools like Claude would mid-turn."""

    bridge: JarvisToolBridge
    script: tuple[tuple[str, str], ...] = ()
    session_id: str | None = "sess-bridge"
    tool_results: list[str] = field(default_factory=list)

    def ask(self, command: str, *, confirmed: bool = False) -> BrainTurn:
        replies: list[str] = []
        for tool, arg in self.script:
            res = self.bridge.call_tool(tool, {"command": arg})
            self.tool_results.append(res.text)
            replies.append(res.text)
        return BrainTurn(
            reply=" ".join(replies) or "Done.",
            session_id=self.session_id,
            ok=True,
        )


def _fake_apps(launches: list[str]) -> AppHandler:
    return AppHandler(
        ops={
            "find_windows": lambda **kw: [],
            "focus": lambda hwnd: None,
            "launch": lambda spec, force_new=False: launches.append(spec.key),
        }
    )


def test_open_spotify_then_next_track_end_to_end() -> None:
    bus = EventBus()
    events: list[Any] = []
    bus.subscribe(events.append)

    launches: list[str] = []
    player = FakeSpotifyPlayer()
    bridge = JarvisToolBridge(
        bus=bus,
        apps=_fake_apps(launches),
        spotify=sample_spotify(player=player),
    )
    brain = ScriptedBridgeBrain(
        bridge=bridge,
        script=(
            ("apps", "open spotify"),
            ("spotify", "play the next track"),
        ),
    )
    speaker = FakeSpeaker()

    result = handle_command(
        "open spotify and play the next track", brain=brain, speaker=speaker
    )

    # Both domains actually fired.
    assert launches == ["spotify"], "apps.open did not launch Spotify"
    assert "next" in player.calls, "spotify.next did not skip the track"

    # Bus events ordered Start→Finish per call: apps then spotify.
    steps = [
        (type(e).__name__, e.name)
        for e in events
        if isinstance(e, (StepStarted, StepFinished))
    ]
    assert steps == [
        ("StepStarted", "apps"),
        ("StepFinished", "apps"),
        ("StepStarted", "spotify"),
        ("StepFinished", "spotify"),
    ]

    # A spoken reply was produced through the core.
    assert result.ok
    assert result.reply.strip()
    assert speaker.spoken, "nothing was spoken"
    assert "Skipped." in result.reply
