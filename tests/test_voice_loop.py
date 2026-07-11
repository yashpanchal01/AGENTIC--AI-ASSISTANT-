"""Voice path feeds raw transcript into the same handle_command seam."""

from __future__ import annotations

import numpy as np

from jarvis.audio.capture import MicRecorder
from jarvis.audio.silence import SilenceConfig
from jarvis.brain.fake import FakeBrain
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


def test_listen_and_handle_uses_transcript_not_polish() -> None:
    # STT returns messy raw text; brain receives it as-is (FakeTranscriber has no polish).
    raw = "open broadcourt"
    brain = FakeBrain(
        script=[
            BrainTurn(
                reply="Opened Claude Code.",
                actions=(Action(name="launch_app", detail="Claude Code"),),
            )
        ]
    )
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text=raw)
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

    assert outcome.ok
    assert outcome.transcript == raw
    assert outcome.command is not None
    assert outcome.command.reply == "Opened Claude Code."
    assert speaker.spoken == ["Opened Claude Code."]
    assert len(stt.calls) == 1


def test_listen_no_speech_does_not_call_brain() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="should not run", actions=())]
    )
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="hello")
    # Only silence — tracker ends on max_lead_silence without speech.
    sr = 16_000
    quiet = [np.zeros(sr, dtype=np.float32)]  # 1.0 s
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

    assert not outcome.ok
    assert outcome.error == "no_speech"
    assert outcome.command is None
    assert stt.calls == []
    # Plain-language spoken feedback (not silent); brain still not called.
    assert len(speaker.spoken) == 1
    assert speaker.spoken[0]


def test_empty_transcript_skips_brain() -> None:
    brain = FakeBrain()
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
    assert len(speaker.spoken) == 1
    assert speaker.spoken[0]
