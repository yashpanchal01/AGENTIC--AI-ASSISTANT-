"""Voice front door: mic → silence end → STT → same handle_command path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from jarvis.audio.capture import MicRecorder, RecordResult
from jarvis.brain.base import Brain
from jarvis.core import CommandResult, handle_command
from jarvis.plain_replies import plain_error_reply
from jarvis.stt.base import Transcriber
from jarvis.tts.base import Speaker

if TYPE_CHECKING:
    from jarvis.connectivity import Connectivity


@dataclass(frozen=True)
class ListenResult:
    """Outcome of one listen → transcribe → handle_command cycle."""

    transcript: str
    command: CommandResult | None
    record: RecordResult
    error: str | None = None

    @property
    def ok(self) -> bool:
        if self.error:
            return False
        if self.command is None:
            return False
        return self.command.ok


def _maybe_unload_stt(transcriber: Transcriber, *, unload: bool) -> None:
    if not unload:
        return
    unload_fn = getattr(transcriber, "unload", None)
    if callable(unload_fn):
        try:
            unload_fn()
        except Exception:  # noqa: BLE001 — VRAM free is best-effort
            pass


def listen_and_handle(
    *,
    recorder: MicRecorder,
    transcriber: Transcriber,
    brain: Brain,
    speaker: Speaker,
    google=None,
    connectivity: Connectivity | None = None,
    unload_stt_after: bool = False,
) -> ListenResult:
    """Record until silence, transcribe raw text, feed handle_command.

    No intermediate polish model — transcript goes straight to the brain.
    Local failures (no speech, empty transcript, STT crash) are spoken in
    plain language so nothing fails silently. Optional *unload_stt_after*
    releases the transcription model between commands (VRAM coexistence).
    """
    record = recorder.record_until_silence()
    if record.audio.size == 0 or not record.heard_speech:
        reply = plain_error_reply("no_speech")
        speaker.speak(reply)
        return ListenResult(
            transcript="",
            command=None,
            record=record,
            error="no_speech",
        )

    try:
        transcript = (
            transcriber.transcribe(record.audio, sample_rate=record.sample_rate) or ""
        ).strip()
    except Exception:  # noqa: BLE001 — STT must not freeze the loop
        _maybe_unload_stt(transcriber, unload=unload_stt_after)
        reply = plain_error_reply("stt_failed")
        speaker.speak(reply)
        return ListenResult(
            transcript="",
            command=None,
            record=record,
            error="stt_failed",
        )

    _maybe_unload_stt(transcriber, unload=unload_stt_after)

    if not transcript:
        reply = plain_error_reply("empty_transcript")
        speaker.speak(reply)
        return ListenResult(
            transcript="",
            command=None,
            record=record,
            error="empty_transcript",
        )

    result = handle_command(
        transcript,
        brain=brain,
        speaker=speaker,
        google=google,
        connectivity=connectivity,
    )
    return ListenResult(transcript=transcript, command=result, record=record)
