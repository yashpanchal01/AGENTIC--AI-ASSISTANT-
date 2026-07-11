"""Behavioral tests for graceful degradation (GitHub issue #9 / Slice 10).

Seams under test:
  - handle_command(transcript, brain, speaker, connectivity?) → spoken reply + flags
  - listen_and_handle(...) → spoken plain-language on local failures
  - Transcriber.unload() → model released (VRAM coexistence fallback)

Assertions are external only: reply text, spoken output, ok/error, unload calls.
"""

from __future__ import annotations

import numpy as np

from jarvis.audio.capture import MicRecorder
from jarvis.audio.silence import SilenceConfig
from jarvis.brain.fake import FakeBrain
from jarvis.connectivity import FakeConnectivity
from jarvis.core import handle_command
from jarvis.stt.fake import FakeTranscriber
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import Action, BrainTurn
from jarvis.voice import listen_and_handle


def _speech_then_silence(
    *,
    speech_s: float = 0.5,
    silence_s: float = 1.0,
    sr: int = 16_000,
) -> list[np.ndarray]:
    speech = np.full(int(sr * speech_s), 0.2, dtype=np.float32)
    quiet = np.zeros(int(sr * silence_s), dtype=np.float32)
    return [speech, quiet]


# ---------------------------------------------------------------------------
# Offline honesty — brain gated, local path stays usable
# ---------------------------------------------------------------------------


def test_offline_speaks_brain_unreachable_without_calling_brain() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="should not run", actions=())])
    speaker = FakeSpeaker()
    net = FakeConnectivity(online=False)

    result = handle_command(
        "open notepad",
        brain=brain,
        speaker=speaker,
        connectivity=net,
    )

    assert result.ok is False
    assert result.error == "brain_unreachable"
    assert result.actions == ()
    assert "brain" in result.reply.lower() and "unreachable" in result.reply.lower()
    assert speaker.spoken == [result.reply]
    assert brain._history == []
    assert brain._script_i == 0


def test_online_calls_brain_as_usual() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="Opened Notepad.", actions=())])
    speaker = FakeSpeaker()
    net = FakeConnectivity(online=True)

    result = handle_command(
        "open notepad",
        brain=brain,
        speaker=speaker,
        connectivity=net,
    )

    assert result.ok is True
    assert result.reply == "Opened Notepad."
    assert speaker.spoken == ["Opened Notepad."]
    assert brain._history == ["open notepad"]


def test_brain_network_failure_is_spoken_as_unreachable() -> None:
    """Brain throws / returns network failure → plain spoken offline message."""

    class NetworkBrain:
        def ask(self, command: str):
            raise ConnectionError("Failed to resolve host")

    speaker = FakeSpeaker()
    result = handle_command("what's the weather?", brain=NetworkBrain(), speaker=speaker)

    assert result.ok is False
    assert result.error == "brain_unreachable"
    assert "unreachable" in result.reply.lower()
    assert speaker.spoken == [result.reply]


# ---------------------------------------------------------------------------
# Spoken plain-language failures — never silent death
# ---------------------------------------------------------------------------


def test_failed_action_is_explained_aloud() -> None:
    brain = FakeBrain(
        script=[
            BrainTurn(
                reply="I couldn't find that file.",
                actions=(),
                ok=False,
                error="not_found",
            )
        ]
    )
    speaker = FakeSpeaker()

    result = handle_command(
        "open the invoices PDF from last week",
        brain=brain,
        speaker=speaker,
    )

    assert result.ok is False
    assert result.reply == "I couldn't find that file."
    assert speaker.spoken == ["I couldn't find that file."]


def test_empty_failure_reply_gets_plain_language_fallback() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="", actions=(), ok=False, error="tool_failed")]
    )
    speaker = FakeSpeaker()

    result = handle_command("do the thing", brain=brain, speaker=speaker)

    assert result.ok is False
    assert result.reply  # never empty
    assert "wrong" in result.reply.lower() or "couldn't" in result.reply.lower()
    assert speaker.spoken == [result.reply]


def test_refusal_is_spoken_with_reason() -> None:
    """Hard-denied secrets (and ask-first declines) always produce a spoken reply."""
    brain = FakeBrain()
    speaker = FakeSpeaker()

    result = handle_command(
        "read my password from the vault",
        brain=brain,
        speaker=speaker,
    )

    assert result.denied is True
    assert result.actions == ()
    assert speaker.spoken
    assert result.reply  # plain reason, never silent


def test_generic_brain_exception_is_spoken_plainly() -> None:
    class BoomBrain:
        def ask(self, command: str):
            raise RuntimeError("internal boom")

    speaker = FakeSpeaker()
    result = handle_command("hello", brain=BoomBrain(), speaker=speaker)

    assert result.ok is False
    assert speaker.spoken == [result.reply]
    assert "stack" not in result.reply.lower()
    assert "traceback" not in result.reply.lower()
    assert "RuntimeError" not in result.reply


# ---------------------------------------------------------------------------
# Voice path — local failures spoken; STT unload for VRAM
# ---------------------------------------------------------------------------


def test_voice_empty_transcript_is_spoken_not_silent() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="should not run", actions=())])
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="   ")
    rec = MicRecorder(
        config=SilenceConfig(silence_duration_s=0.5, min_speech_s=0.2),
        blocks=_speech_then_silence(silence_s=0.8),
    )

    outcome = listen_and_handle(
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
    )

    assert outcome.error == "empty_transcript"
    assert outcome.command is None
    assert speaker.spoken  # plain language, not silent
    assert brain._history == []


def test_voice_no_speech_is_spoken_not_silent() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="should not run", actions=())])
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="hello")
    sr = 16_000
    quiet = [np.zeros(sr, dtype=np.float32)]
    rec = MicRecorder(
        config=SilenceConfig(max_lead_silence_s=0.5, max_record_s=5.0),
        blocks=quiet,
    )

    outcome = listen_and_handle(
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
    )

    assert outcome.error == "no_speech"
    assert speaker.spoken
    assert stt.calls == []


def test_offline_voice_path_still_transcribes_then_speaks_unreachable() -> None:
    """Wake/record/STT stay local; brain is skipped when offline."""
    brain = FakeBrain(script=[BrainTurn(reply="should not run", actions=())])
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="open notepad")
    rec = MicRecorder(
        config=SilenceConfig(silence_duration_s=0.5, min_speech_s=0.2),
        blocks=_speech_then_silence(silence_s=0.8),
    )
    net = FakeConnectivity(online=False)

    outcome = listen_and_handle(
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        connectivity=net,
    )

    assert outcome.transcript == "open notepad"
    assert len(stt.calls) == 1  # STT still ran
    assert outcome.command is not None
    assert outcome.command.error == "brain_unreachable"
    assert "unreachable" in outcome.command.reply.lower()
    assert speaker.spoken == [outcome.command.reply]
    assert brain._history == []


def test_stt_unload_between_commands_when_enabled() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="Opened Notepad.", actions=(Action("launch_app", "Notepad"),))]
    )
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="open notepad")
    rec = MicRecorder(
        config=SilenceConfig(silence_duration_s=0.5, min_speech_s=0.2),
        blocks=_speech_then_silence(silence_s=0.8),
    )

    outcome = listen_and_handle(
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        unload_stt_after=True,
    )

    assert outcome.ok
    assert stt.unload_calls == 1


def test_stt_unload_not_called_when_disabled() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="Done.", actions=())])
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="hello")
    rec = MicRecorder(
        config=SilenceConfig(silence_duration_s=0.5, min_speech_s=0.2),
        blocks=_speech_then_silence(silence_s=0.8),
    )

    listen_and_handle(
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        unload_stt_after=False,
    )

    assert stt.unload_calls == 0
