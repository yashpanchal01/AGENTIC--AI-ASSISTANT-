"""Behavioral tests for the headless core loop seam.

Seam (from PRD): handle_command(transcript_text) → reply + actions taken.
Assertions are on external behavior only — reply text, actions, spoken output.
"""

from __future__ import annotations

from jarvis.brain.fake import FakeBrain
from jarvis.core import handle_command
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import Action, BrainTurn


def test_question_returns_reply_and_speaks_it() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="It's about 72 degrees.", actions=())]
    )
    speaker = FakeSpeaker()

    result = handle_command("what's the weather?", brain=brain, speaker=speaker)

    assert result.reply == "It's about 72 degrees."
    assert result.actions == ()
    assert speaker.spoken == ["It's about 72 degrees."]
    assert result.ok is True


def test_safe_tier_action_is_reported_and_spoken() -> None:
    brain = FakeBrain(
        script=[
            BrainTurn(
                reply="Opened Notepad.",
                actions=(Action(name="launch_app", detail="Notepad"),),
            )
        ]
    )
    speaker = FakeSpeaker()

    result = handle_command("open notepad", brain=brain, speaker=speaker)

    assert result.reply == "Opened Notepad."
    assert len(result.actions) == 1
    assert result.actions[0].name == "launch_app"
    assert result.actions[0].detail == "Notepad"
    assert speaker.spoken == ["Opened Notepad."]


def test_risky_action_does_not_auto_run() -> None:
    """Risky actions never auto-run without an explicit yes (issue 06)."""
    brain = FakeBrain()
    speaker = FakeSpeaker()

    result = handle_command(
        "delete C:\\Windows\\System32",
        brain=brain,
        speaker=speaker,
    )

    # No confirmer → safe decline; zero actions executed.
    assert result.actions == ()
    assert result.error == "confirmation_declined"
    assert speaker.spoken  # still speaks the ask + cancel


def test_secrets_are_never_touched() -> None:
    brain = FakeBrain()
    speaker = FakeSpeaker()

    result = handle_command(
        "read my password from the secrets file",
        brain=brain,
        speaker=speaker,
    )

    assert result.denied is True
    assert result.actions == ()
    assert speaker.spoken


def test_persistent_session_carries_context_for_corrections() -> None:
    brain = FakeBrain()
    speaker = FakeSpeaker()

    first = handle_command("open notepad", brain=brain, speaker=speaker)
    second = handle_command("actually, close it", brain=brain, speaker=speaker)

    assert first.actions[0].name == "launch_app"
    assert second.actions[0].name == "close_app"
    assert "notepad" in second.reply.lower()
    assert second.session_id == first.session_id
    assert speaker.spoken == [first.reply, second.reply]


def test_persistent_session_remembers_prior_fact() -> None:
    brain = FakeBrain()
    speaker = FakeSpeaker()

    handle_command("remember that the code is blue", brain=brain, speaker=speaker)
    result = handle_command("what is the code?", brain=brain, speaker=speaker)

    assert "blue" in result.reply.lower()
    assert result.session_id is not None


def test_empty_transcript_is_rejected_without_calling_brain() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="should not run", actions=())]
    )
    speaker = FakeSpeaker()

    result = handle_command("   ", brain=brain, speaker=speaker)

    assert result.ok is False
    assert result.reply
    assert speaker.spoken == []  # nothing to say for empty input
    assert brain._history == []
    assert brain._script_i == 0


def test_brain_exception_becomes_failed_result() -> None:
    class BoomBrain:
        def ask(self, command: str):
            raise RuntimeError("boom")

    speaker = FakeSpeaker()
    result = handle_command("hello", brain=BoomBrain(), speaker=speaker)
    assert result.ok is False
    assert result.actions == ()
    assert "brain" in result.reply.lower() or "wrong" in result.reply.lower()


# -- Fault breadth (issue 23): any tier's failed turn faults exactly once ------

import pytest

from jarvis.core import CommandResult, should_fault
from jarvis.events import EventBus, Fault


def _faults(events: list[object]) -> list[Fault]:
    return [e for e in events if isinstance(e, Fault)]


def _capture_bus() -> tuple[EventBus, list[object]]:
    bus = EventBus()
    events: list[object] = []
    bus.subscribe(events.append)
    return bus, events


@pytest.mark.parametrize(
    ("ok", "denied", "error", "faults"),
    [
        # Honest failures → fault (spoken error must flash the overlay).
        (False, False, "brightness_unsupported", True),
        (False, False, "no_window", True),  # app launched, window never appeared
        (False, False, "not_found", True),  # media / capture / window lookup
        (False, False, "not_running", True),  # focus target missing
        (False, False, "timeout", True),
        (False, False, "brain_unreachable", True),  # offline tier included
        (False, False, "spotify_unreachable", True),
        (False, False, "google_unreachable", True),
        (False, False, "rate_limited", True),
        (False, False, "RuntimeError", True),  # boundary exception names
        (False, False, None, True),  # unknown failure → fail-visible default
        # Deliberate non-actions → NO fault (JARVIS working correctly).
        (True, False, None, False),  # plain success
        (True, False, "confirmation_declined", False),  # user said no
        (True, False, "confirmation_incomplete", False),
        (False, False, "cancelled", False),  # user aborted on purpose
        (True, False, "busy", False),  # still-working refusal
        (True, False, "already_finished", False),
        (False, False, "not_configured", False),  # "Spotify isn't set up"
        (False, False, "not_signed_in", False),  # login pointer
        (False, False, "empty_transcript", False),  # nothing to act on
        (False, True, "secret_denied", False),  # hard-deny / secret tier
        (False, True, None, False),  # any denied outcome
    ],
)
def test_fault_classification_table(
    ok: bool, denied: bool, error: str | None, faults: bool
) -> None:
    result = CommandResult(reply="x", actions=(), ok=ok, denied=denied, error=error)
    assert should_fault(result) is faults


def test_reflex_brightness_failure_faults_once() -> None:
    from jarvis.system.brightness import BrightnessError
    from jarvis.system.handler import SystemHandler

    def _no_brightness(level: int) -> None:
        raise BrightnessError("This display doesn't support brightness control.")

    system = SystemHandler(
        capture_roots=(),
        get_brightness=lambda: 50,
        set_brightness=_no_brightness,
        open_fn=lambda path: None,
    )
    bus, events = _capture_bus()

    result = handle_command(
        "set brightness to 80 percent",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        system=system,
        bus=bus,
    )

    assert result.ok is False and result.error == "brightness_unsupported"
    assert len(_faults(events)) == 1
    assert _faults(events)[0].error == "brightness_unsupported"


def test_reflex_app_launch_failure_faults_once() -> None:
    from jarvis.apps.handler import AppHandler

    apps = AppHandler(
        ops={
            "find_windows": lambda **kw: [],  # window never appears
            "focus": lambda hwnd: None,
            "launch": lambda spec, force_new=False: None,
        },
        verify_timeout_s=0.0,
        verify_poll_s=0.0,
    )
    bus, events = _capture_bus()

    result = handle_command(
        "open brave",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        apps=apps,
        bus=bus,
    )

    assert result.ok is False and result.error == "no_window"
    assert len(_faults(events)) == 1


def test_offline_brain_unreachable_faults_once() -> None:
    class OfflineConnectivity:
        def is_online(self) -> bool:
            return False

    bus, events = _capture_bus()

    result = handle_command(
        "what's the weather?",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        connectivity=OfflineConnectivity(),
        bus=bus,
    )

    assert result.ok is False and result.error == "brain_unreachable"
    assert len(_faults(events)) == 1


def test_failed_brain_turn_faults_exactly_once() -> None:
    # Regression for the issue 23 hoist: the brain-boundary publisher is gone,
    # so a failed brain turn must fault ONCE at the core seam — never twice.
    brain = FakeBrain(
        script=[BrainTurn(reply="I couldn't do that.", ok=False, error="task_failed")]
    )
    bus, events = _capture_bus()

    result = handle_command(
        "do the impossible", brain=brain, speaker=FakeSpeaker(), bus=bus
    )

    assert result.ok is False
    assert len(_faults(events)) == 1


def test_deliberate_non_actions_do_not_fault() -> None:
    bus, events = _capture_bus()
    speaker = FakeSpeaker()

    # Secret-tier hard deny.
    denied = handle_command(
        "read my password from the secrets file",
        brain=FakeBrain(),
        speaker=speaker,
        bus=bus,
    )
    assert denied.denied is True

    # Ask-first proposal with no confirmer → safe decline.
    declined = handle_command(
        "delete C:\\Windows\\System32",
        brain=FakeBrain(),
        speaker=speaker,
        bus=bus,
    )
    assert declined.error == "confirmation_declined"

    # Spotify "not set up" pointer.
    from jarvis.spotify.controller import SpotifyControllerImpl

    pointer = handle_command(
        "play some jazz",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=SpotifyControllerImpl(configured=False),
        bus=bus,
    )
    assert pointer.error == "not_configured"

    assert _faults(events) == []


def test_successful_turn_publishes_no_fault() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="Done.", actions=())])
    bus, events = _capture_bus()

    result = handle_command("hello", brain=brain, speaker=FakeSpeaker(), bus=bus)

    assert result.ok is True
    assert _faults(events) == []


def test_backgrounded_long_task_failure_faults_once() -> None:
    import time

    from jarvis.tasks import LongTaskService

    class SlowFailBrain:
        def ask(self, command: str) -> BrainTurn:
            time.sleep(0.2)
            return BrainTurn(reply="", ok=False, error="task_failed")

    bus, events = _capture_bus()
    long_tasks = LongTaskService(threshold_s=0.01)

    result = handle_command(
        "do a slow thing",
        brain=SlowFailBrain(),
        speaker=FakeSpeaker(),
        long_tasks=long_tasks,
        bus=bus,
    )

    # The "On it." ack is a success — no fault yet.
    assert result.backgrounded is True
    assert _faults(events) == []

    assert long_tasks.wait(timeout=5.0)
    assert len(_faults(events)) == 1
