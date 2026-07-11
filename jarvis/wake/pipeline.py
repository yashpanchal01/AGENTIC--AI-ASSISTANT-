"""Shared armed command path — used by both wake-word and hotkey front doors.

Contract:
  record → whisper → (optional wake-phrase strip) → brain → Piper

Wake is required again for every new command (caller returns to wait_for_trigger).
No open-mic follow-up window lives here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Literal

from jarvis.audio.capture import MicRecorder, RecordResult
from jarvis.brain.base import Brain
from jarvis.core import handle_command
from jarvis.overlay.base import Overlay
from jarvis.overlay.states import OverlayState
from jarvis.plain_replies import plain_error_reply
from jarvis.stt.base import Transcriber
from jarvis.tts.base import Speaker
from jarvis.voice import ListenResult, _maybe_unload_stt
from jarvis.wake.phrases import DEFAULT_WAKE_PHRASES, strip_wake_phrase

if TYPE_CHECKING:
    from jarvis.connectivity import Connectivity

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
    *,
    unload_stt_after: bool = False,
) -> tuple[str, str | None]:
    """Return (transcript, error_code). Speaks nothing — caller speaks on error."""
    if record.audio.size == 0 or not record.heard_speech:
        return "", "no_speech"
    try:
        text = (
            transcriber.transcribe(record.audio, sample_rate=record.sample_rate) or ""
        ).strip()
    except Exception:  # noqa: BLE001 — STT must not freeze the armed path
        _maybe_unload_stt(transcriber, unload=unload_stt_after)
        return "", "stt_failed"
    _maybe_unload_stt(transcriber, unload=unload_stt_after)
    if not text:
        return "", "empty_transcript"
    return text, None


def _speak_local_error(speaker: Speaker, error: str) -> None:
    try:
        speaker.speak(plain_error_reply(error))
    except Exception:  # noqa: BLE001 — still return the error code
        pass


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
    connectivity: Connectivity | None = None,
    unload_stt_after: bool = False,
) -> ListenResult:
    """Single command after arming (wake or hotkey). Shared entry point.

    One-breath (wake): transcript may still contain the wake phrase — strip it.
    Two-step (wake): if only the wake phrase remains, acknowledge and record again.
    Hotkey: no wake stripping; one record → STT → handle_command.

    Local failures are spoken in plain language. Overlay always returns to REST.
    ARMED is only held while the mic is recording (not during STT).
    """
    if overlay is not None:
        overlay.set_state(OverlayState.ARMED)

    rest_owned_by_handler = False
    try:
        record = recorder.record_until_silence()
        # Mic is no longer hot — leave ARMED before multi-second STT.
        if overlay is not None:
            overlay.set_state(OverlayState.WORKING)

        raw, err = _transcribe_record(
            record, transcriber, unload_stt_after=unload_stt_after
        )
        if err:
            _speak_local_error(speaker, err)
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
                    try:
                        speaker.speak(acknowledge_text)
                    except Exception:
                        pass
                if overlay is not None:
                    overlay.set_state(OverlayState.ARMED)

                record = recorder.record_until_silence()
                if overlay is not None:
                    overlay.set_state(OverlayState.WORKING)

                raw2, err2 = _transcribe_record(
                    record, transcriber, unload_stt_after=unload_stt_after
                )
                if err2:
                    _speak_local_error(speaker, err2)
                    return ListenResult(
                        transcript=raw2,
                        command=None,
                        record=record,
                        error=err2,
                    )
                command_text = strip_wake_phrase(raw2, wake_phrases) or raw2
                raw = raw2

        if not command_text.strip():
            _speak_local_error(speaker, "empty_transcript")
            return ListenResult(
                transcript=raw,
                command=None,
                record=record,
                error="empty_transcript",
            )

        if overlay is not None:
            from jarvis.overlay.lifecycle import handle_command_with_overlay

            rest_owned_by_handler = True
            result = handle_command_with_overlay(
                command_text,
                brain=brain,
                speaker=speaker,
                overlay=overlay,
                google=google,
                connectivity=connectivity,
            )
        else:
            result = handle_command(
                command_text,
                brain=brain,
                speaker=speaker,
                google=google,
                connectivity=connectivity,
            )

        return ListenResult(
            transcript=command_text,
            command=result,
            record=record,
        )
    finally:
        if overlay is not None and not rest_owned_by_handler:
            overlay.set_state(OverlayState.REST)
