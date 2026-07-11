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
