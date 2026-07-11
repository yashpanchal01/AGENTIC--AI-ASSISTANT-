"""Behavioral tests for long-running tasks (issue 10 / PRD stories 44–45).

Detection: timeout race — brain.ask runs on a worker; if still running past
the threshold, JARVIS speaks "On it.", returns backgrounded, keeps overlay
WORKING, and announces completion/failure (or cancel) later.

Assertions are external only: reply text, spoken lines, actions, overlay
states, CommandResult.backgrounded / ok / error.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from jarvis.brain.fake import FakeBrain
from jarvis.core import handle_command
from jarvis.overlay.fake import FakeOverlay
from jarvis.overlay.lifecycle import handle_command_with_overlay
from jarvis.overlay.states import OverlayState
from jarvis.plain_replies import (
    ALREADY_FINISHED,
    CANCELLED,
    NOTHING_TO_CANCEL,
    ON_IT,
    STILL_WORKING,
)
from jarvis.tasks import LongTaskService, is_cancel_utterance
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import Action, BrainTurn


# ---------------------------------------------------------------------------
# Cancel utterance detection
# ---------------------------------------------------------------------------


def test_is_cancel_utterance_variants() -> None:
    assert is_cancel_utterance("cancel")
    assert is_cancel_utterance("Cancel.")
    assert is_cancel_utterance("Jarvis, cancel")
    assert is_cancel_utterance("jarvis cancel that")
    assert is_cancel_utterance("stop")
    assert is_cancel_utterance("never mind")
    assert is_cancel_utterance("please cancel")
    assert not is_cancel_utterance("open notepad")
    assert not is_cancel_utterance("cancel my calendar for next week")
    # Real commands must not be swallowed as cancel (#4).
    assert not is_cancel_utterance("stop the music")
    assert not is_cancel_utterance("stop timer")
    assert not is_cancel_utterance("abort download")
    assert not is_cancel_utterance("dont cancel")
    assert not is_cancel_utterance("cancel my meeting")


def test_idle_false_positive_cancel_phrases_go_to_brain() -> None:
    """When idle, non-exact 'stop …' phrases must reach the brain (#4)."""
    brain = FakeBrain(
        script=[BrainTurn(reply="Paused Spotify.", actions=(Action("spotify", "pause"),))]
    )
    speaker = FakeSpeaker()
    tasks = LongTaskService(threshold_s=1.0)

    result = handle_command(
        "stop the music",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )

    assert result.reply == "Paused Spotify."
    assert brain._history == ["stop the music"]
    assert NOTHING_TO_CANCEL not in speaker.spoken
    assert CANCELLED not in speaker.spoken


# ---------------------------------------------------------------------------
# Short path unchanged
# ---------------------------------------------------------------------------


def test_short_command_stays_foreground_with_long_tasks() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="Opened Notepad.", actions=(Action("launch_app", "Notepad"),))],
        delay_s=0.0,
    )
    speaker = FakeSpeaker()
    tasks = LongTaskService(threshold_s=0.5)

    result = handle_command(
        "open notepad",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )

    assert result.backgrounded is False
    assert result.ok is True
    assert result.reply == "Opened Notepad."
    assert speaker.spoken == ["Opened Notepad."]
    assert not tasks.busy


def test_short_command_without_long_tasks_unchanged() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="Hi.", actions=())])
    speaker = FakeSpeaker()
    result = handle_command("hello", brain=brain, speaker=speaker)
    assert result.backgrounded is False
    assert result.reply == "Hi."
    assert speaker.spoken == ["Hi."]


# ---------------------------------------------------------------------------
# Background + ack + completion
# ---------------------------------------------------------------------------


def test_long_work_backgrounded_with_spoken_ack() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="Refactor finished.", actions=(Action("edit", "main.py"),))],
        delay_s=0.35,
    )
    speaker = FakeSpeaker()
    tasks = LongTaskService(threshold_s=0.08)

    t0 = time.monotonic()
    result = handle_command(
        "refactor the project",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )
    elapsed = time.monotonic() - t0

    assert result.backgrounded is True
    assert result.ok is True
    assert result.reply == ON_IT
    assert speaker.spoken[0] == ON_IT
    assert any(a.name == "task_backgrounded" for a in result.actions)
    # Must return well before the full brain delay.
    assert elapsed < 0.30
    assert tasks.busy

    assert tasks.wait(timeout=2.0)
    final = tasks.last_final
    assert final is not None
    assert final.reply == "Refactor finished."
    assert final.ok is True
    assert speaker.spoken == [ON_IT, "Refactor finished."]


def test_long_work_failure_is_announced() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="I couldn't finish that.", ok=False, error="tool_failed")],
        delay_s=0.25,
    )
    speaker = FakeSpeaker()
    tasks = LongTaskService(threshold_s=0.05)

    result = handle_command(
        "do a hard thing",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )
    assert result.backgrounded is True
    assert speaker.spoken == [ON_IT]

    assert tasks.wait(timeout=2.0)
    final = tasks.last_final
    assert final is not None
    assert final.ok is False
    assert "couldn't finish" in final.reply.lower() or final.reply
    assert speaker.spoken[-1] == final.reply
    assert ON_IT in speaker.spoken


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


def test_cancel_aborts_in_flight_long_task() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="should not finish", actions=())],
        delay_s=2.0,
    )
    speaker = FakeSpeaker()
    tasks = LongTaskService(threshold_s=0.05)

    started = handle_command(
        "long multi step job",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )
    assert started.backgrounded is True
    assert tasks.busy

    # Small pause so the brain is mid-delay.
    time.sleep(0.08)
    cancelled = handle_command(
        "Jarvis, cancel",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )

    assert cancelled.reply == CANCELLED
    assert cancelled.error == "cancelled"
    assert cancelled.ok is False
    assert tasks.wait(timeout=2.0)
    assert not tasks.busy
    assert CANCELLED in speaker.spoken
    # Must not announce the original success reply.
    assert "should not finish" not in speaker.spoken
    # No double Cancelled.
    assert speaker.spoken.count(CANCELLED) == 1


def test_cancel_when_idle_speaks_nothing_to_cancel() -> None:
    brain = FakeBrain()
    speaker = FakeSpeaker()
    tasks = LongTaskService(threshold_s=0.5)

    result = handle_command("cancel", brain=brain, speaker=speaker, long_tasks=tasks)

    assert result.reply == NOTHING_TO_CANCEL
    assert speaker.spoken == [NOTHING_TO_CANCEL]
    assert brain._history == []  # cancel does not call brain.ask


def test_busy_refuses_second_non_cancel_command() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="done late", actions=())],
        delay_s=0.5,
    )
    speaker = FakeSpeaker()
    tasks = LongTaskService(threshold_s=0.05)

    first = handle_command("slow job", brain=brain, speaker=speaker, long_tasks=tasks)
    assert first.backgrounded is True

    second = handle_command("open notepad", brain=brain, speaker=speaker, long_tasks=tasks)
    assert second.reply == STILL_WORKING
    assert second.error == "busy"
    assert speaker.spoken[-1] == STILL_WORKING

    # Clean up so the suite doesn't leave a dangling thread mid-delay.
    handle_command("cancel", brain=brain, speaker=speaker, long_tasks=tasks)
    tasks.wait(timeout=2.0)


@dataclass
class _HangBrain:
    """No-op cancel + long ask — exercises force-clear / generation safety (#2)."""

    delay_s: float = 1.5
    reply: str = "late success"
    history: list[str] = field(default_factory=list)
    cancel_calls: int = 0

    def cancel(self) -> None:
        self.cancel_calls += 1
        # Intentionally does not interrupt ask().

    def ask(self, command: str) -> BrainTurn:
        self.history.append(command)
        time.sleep(self.delay_s)
        return BrainTurn(reply=self.reply, ok=True)


def test_noop_cancel_does_not_double_speak_or_start_second_task() -> None:
    brain = _HangBrain(delay_s=0.6, reply="should not be heard twice")
    speaker = FakeSpeaker()
    tasks = LongTaskService(threshold_s=0.05, cancel_wait_s=0.15)

    started = handle_command(
        "hang forever job",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )
    assert started.backgrounded is True

    cancelled = handle_command(
        "cancel",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )
    assert cancelled.reply == CANCELLED
    assert brain.cancel_calls >= 1

    # While the hung worker is still draining, a new long task must be refused.
    second = handle_command(
        "another long thing",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )
    assert second.error == "busy"
    assert second.reply == STILL_WORKING

    # Wait for the original worker to finish; stale watcher must not re-speak.
    assert tasks.wait(timeout=3.0)
    assert speaker.spoken.count(CANCELLED) == 1
    assert "should not be heard twice" not in speaker.spoken
    assert not tasks.busy


@dataclass
class _SlowSpeakSpeaker:
    """FakeSpeaker that blocks on a chosen phrase so cancel can race announce (#3)."""

    spoken: list[str] = field(default_factory=list)
    block_on: str = "SUCCESS"
    block_s: float = 0.35

    def speak(self, text: str) -> None:
        if text == self.block_on:
            time.sleep(self.block_s)
        self.spoken.append(text)


def test_cancel_after_success_does_not_rewrite_to_cancelled() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="SUCCESS", actions=())],
        delay_s=0.12,
    )
    speaker = _SlowSpeakSpeaker(block_on="SUCCESS", block_s=0.35)
    tasks = LongTaskService(threshold_s=0.04)

    started = handle_command(
        "almost done job",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )
    assert started.backgrounded is True

    # Wait until the success announce is in flight (or finished).
    time.sleep(0.20)
    result = handle_command(
        "cancel",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )

    assert tasks.wait(timeout=2.0)
    # Success must be the authoritative final; cancel must not rewrite it.
    final = tasks.last_final
    assert final is not None
    assert final.error != "cancelled" or result.error == "already_finished"
    if result.error == "already_finished":
        assert result.reply == ALREADY_FINISHED
        assert speaker.spoken.count(CANCELLED) == 0
    # Never: On it + SUCCESS + Cancelled as a force rewrite of success.
    if "SUCCESS" in speaker.spoken:
        assert speaker.spoken.count(CANCELLED) == 0
        assert final.reply == "SUCCESS"


def test_force_cancel_mid_announce_does_not_speak_cancelled_then_success() -> None:
    """Worker dead + slow completion TTS + short cancel_wait must not force Cancelled.

    Reproduces residual race: cancel_wait expires while SUCCESS is mid-speak,
    old force path published cancelled and spoke Cancelled., then SUCCESS finished.
    """
    brain = FakeBrain(
        script=[BrainTurn(reply="SUCCESS", actions=())],
        delay_s=0.08,
    )
    speaker = _SlowSpeakSpeaker(block_on="SUCCESS", block_s=0.50)
    tasks = LongTaskService(
        threshold_s=0.03,
        cancel_wait_s=0.08,  # expires during SUCCESS speak
        announce_wait_s=2.0,
    )

    started = handle_command(
        "finishing job",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )
    assert started.backgrounded is True

    # Land cancel while completion speak is blocking.
    time.sleep(0.12)
    result = handle_command(
        "cancel",
        brain=brain,
        speaker=speaker,
        long_tasks=tasks,
    )

    assert tasks.wait(timeout=3.0)
    final = tasks.last_final
    assert final is not None
    assert final.reply == "SUCCESS"
    assert final.error != "cancelled"
    assert result.error == "already_finished"
    assert result.reply == ALREADY_FINISHED
    # No Cancelled. at all — force path must not run when worker is dead.
    assert CANCELLED not in speaker.spoken
    assert "SUCCESS" in speaker.spoken
    # Spoken order must not be Cancelled then SUCCESS.
    if CANCELLED in speaker.spoken and "SUCCESS" in speaker.spoken:
        assert speaker.spoken.index("SUCCESS") < speaker.spoken.index(CANCELLED)


# ---------------------------------------------------------------------------
# Overlay stays WORKING while backgrounded
# ---------------------------------------------------------------------------


def test_overlay_stays_working_while_backgrounded_then_announces() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="All done.", actions=())],
        delay_s=0.30,
    )
    speaker = FakeSpeaker()
    overlay = FakeOverlay()
    tasks = LongTaskService(threshold_s=0.06)

    result = handle_command_with_overlay(
        "big multi step task",
        brain=brain,
        speaker=speaker,
        overlay=overlay,
        long_tasks=tasks,
        heard_dwell_s=0,
        speaking_min_s=0,
    )

    assert result.backgrounded is True
    assert result.reply == ON_IT
    # After return, overlay must reflect ongoing work (not REST).
    assert overlay.state is OverlayState.WORKING
    assert OverlayState.WORKING in overlay.states
    assert overlay.states[-1] is OverlayState.WORKING

    assert tasks.wait(timeout=2.0)
    # Completion: spoke result and returned to REST.
    assert "All done." in speaker.spoken
    assert overlay.state is OverlayState.REST
    assert OverlayState.SPEAKING in overlay.states


def test_overlay_stays_working_after_busy_secondary_command() -> None:
    """Concurrent non-cancel must not drop overlay to REST while busy (#1)."""
    brain = FakeBrain(
        script=[BrainTurn(reply="All done.", actions=())],
        delay_s=0.45,
    )
    speaker = FakeSpeaker()
    overlay = FakeOverlay()
    tasks = LongTaskService(threshold_s=0.05)

    first = handle_command_with_overlay(
        "long multi step",
        brain=brain,
        speaker=speaker,
        overlay=overlay,
        long_tasks=tasks,
        heard_dwell_s=0,
        speaking_min_s=0,
    )
    assert first.backgrounded is True
    assert overlay.state is OverlayState.WORKING
    assert tasks.busy

    second = handle_command_with_overlay(
        "open notepad",
        brain=brain,
        speaker=speaker,
        overlay=overlay,
        long_tasks=tasks,
        heard_dwell_s=0,
        speaking_min_s=0,
    )
    assert second.reply == STILL_WORKING
    assert second.error == "busy"
    assert tasks.busy
    # Critical: still WORKING, not REST.
    assert overlay.state is OverlayState.WORKING

    assert tasks.wait(timeout=2.0)
    assert overlay.state is OverlayState.REST


def test_overlay_short_path_still_ends_in_rest() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="Quick.", actions=())], delay_s=0.0)
    speaker = FakeSpeaker()
    overlay = FakeOverlay()
    tasks = LongTaskService(threshold_s=1.0)

    result = handle_command_with_overlay(
        "quick question",
        brain=brain,
        speaker=speaker,
        overlay=overlay,
        long_tasks=tasks,
        heard_dwell_s=0,
        speaking_min_s=0,
    )

    assert result.backgrounded is False
    assert result.reply == "Quick."
    assert overlay.states[-1] is OverlayState.REST
    assert speaker.spoken == ["Quick."]


def test_early_cancel_before_ask_is_honored() -> None:
    """cancel() set before ask() body must not be cleared at entry (#6)."""
    brain = FakeBrain(
        script=[BrainTurn(reply="should not run", actions=())],
        delay_s=0.0,
    )
    brain.cancel()  # set before ask
    turn = brain.ask("hello")
    assert turn.error == "cancelled"
    assert "should not run" not in turn.reply
