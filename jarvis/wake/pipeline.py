"""Shared armed command path — used by both wake-word and hotkey front doors.

Contract:
  record → whisper → (optional wake-phrase strip) → brain → Piper

Wake is required again for every new command (caller returns to wait_for_trigger).
No open-mic follow-up window lives here.
"""

from __future__ import annotations

from typing import Callable, Literal

from jarvis.audio.capture import MicRecorder, RecordResult
from jarvis.brain.base import Brain
from jarvis.core import handle_command
from jarvis.overlay.base import Overlay
from jarvis.overlay.states import OverlayState
from jarvis.stt.base import Transcriber
from jarvis.tts.base import Speaker
from jarvis.voice import ListenResult
from jarvis.wake.phrases import DEFAULT_WAKE_PHRASES, strip_wake_phrase

TriggerSource = Literal["wake", "hotkey"]


def _empty_record(sample_rate: int = 16_000) -> RecordResult:
    import numpy as np

    return RecordResult(
        audio=np.zeros(0, dtype=np.float32),
        sample_rate=sample_rate,
        duration_s=0.0,
        heard_speech=False,
    )


def _transcribe_record(
    record: RecordResult,
    transcriber: Transcriber,
) -> tuple[str, str | None]:
    """Return (transcript, error_code)."""
    if record.audio.size == 0 or not record.heard_speech:
        return "", "no_speech"
    text = (transcriber.transcribe(record.audio, sample_rate=record.sample_rate) or "").strip()
    if not text:
        return "", "empty_transcript"
    return text, None


def run_armed_pipeline(
    *,
    recorder: MicRecorder,
    transcriber: Transcriber,
    brain: Brain,
    speaker: Speaker,
    source: TriggerSource,
    overlay: Overlay | None = None,
    google=None,
    wake_phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES,
    on_two_step_ready: Callable[[], None] | None = None,
    acknowledge_text: str | None = "Yes?",
) -> ListenResult:
    """Single command after arming (wake or hotkey). Shared entry point.

    One-breath (wake): transcript may still contain the wake phrase — strip it.
    Two-step (wake): if only the wake phrase remains, acknowledge and record again.
    Hotkey: no wake stripping; one record → STT → handle_command.
    """
    if overlay is not None:
        overlay.set_state(OverlayState.ARMED)

    try:
        record = recorder.record_until_silence()
        raw, err = _transcribe_record(record, transcriber)
        if err:
            return ListenResult(
                transcript=raw,
                command=None,
                record=record,
                error=err,
            )

        command_text = raw
        if source == "wake":
            command_text = strip_wake_phrase(raw, wake_phrases)
            if not command_text:
                # Two-step: wake alone → acknowledge → listen for the command.
                if on_two_step_ready is not None:
                    on_two_step_ready()
                elif acknowledge_text and hasattr(speaker, "speak"):
                    # Brief audible cue; FakeSpeaker records it for assertions.
                    try:
                        speaker.speak(acknowledge_text)
                    except Exception:
                        pass
                if overlay is not None:
                    overlay.set_state(OverlayState.ARMED)

                record = recorder.record_until_silence()
                raw2, err2 = _transcribe_record(record, transcriber)
                if err2:
                    return ListenResult(
                        transcript=raw2,
                        command=None,
                        record=record,
                        error=err2,
                    )
                # Second utterance is the command (still strip if user re-said wake).
                command_text = strip_wake_phrase(raw2, wake_phrases) or raw2
                raw = raw2

        if not command_text.strip():
            return ListenResult(
                transcript=raw,
                command=None,
                record=record,
                error="empty_transcript",
            )

        if overlay is not None:
            from jarvis.overlay.lifecycle import handle_command_with_overlay

            result = handle_command_with_overlay(
                command_text,
                brain=brain,
                speaker=speaker,
                overlay=overlay,
                google=google,
            )
        else:
            result = handle_command(
                command_text, brain=brain, speaker=speaker, google=google
            )

        return ListenResult(
            transcript=command_text,
            command=result,
            record=record,
        )
    finally:
        if overlay is not None:
            overlay.set_state(OverlayState.REST)
