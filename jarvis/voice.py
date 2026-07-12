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
    from jarvis.tasks import LongTaskService


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


def confirmer_may_use_stt(confirmer: object | None) -> bool:
    """True when the confirmer may call STT for voice yes/no (defer unload).

    ``None`` defaults to the live voice path (``VoiceOrClickConfirmer``), which
    needs the model retained through the confirm gate.
    """
    if confirmer is None:
        return True
    return getattr(confirmer, "transcriber", None) is not None


def listen_and_handle(
    *,
    recorder: MicRecorder,
    transcriber: Transcriber,
    brain: Brain,
    speaker: Speaker,
    google=None,
    memory=None,
    spotify=None,
    media=None,
    windows=None,
    apps=None,
    connectivity: Connectivity | None = None,
    long_tasks: LongTaskService | None = None,
    confirmer=None,
    unload_stt_after: bool = False,
    long_task_threshold_s: float | None = None,
    audit=None,
) -> ListenResult:
    """Record until silence, transcribe raw text, feed handle_command.

    No intermediate polish model — transcript goes straight to the brain.
    Local failures (no speech, empty transcript, STT crash) are spoken in
    plain language so nothing fails silently. Optional *unload_stt_after*
    releases the transcription model between commands (VRAM coexistence).
    When a voice confirmer may need STT for yes/no, unload is deferred until
    after ``handle_command`` returns (issue 06).

    *confirmer* wires ask-first yes/no (issue 06) for voice / click backup.
    """
    # Defer unload when voice yes/no may still need Whisper mid-confirm.
    defer_unload = bool(unload_stt_after and confirmer_may_use_stt(confirmer))
    unload_now = bool(unload_stt_after and not defer_unload)

    record = recorder.record_until_silence()
    if record.audio.size == 0 or not record.heard_speech:
        reply = plain_error_reply("no_speech")
        speaker.speak(reply)
        _voice_audit(audit, "transcript_error", error="no_speech")
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
    except Exception as exc:  # noqa: BLE001 — STT must not freeze the loop
        import sys

        print(f"[jarvis stt] {type(exc).__name__}: {exc}", file=sys.stderr)
        _maybe_unload_stt(transcriber, unload=unload_stt_after)
        reply = plain_error_reply("stt_failed")
        speaker.speak(reply)
        _voice_audit(audit, "transcript_error", error="stt_failed")
        return ListenResult(
            transcript="",
            command=None,
            record=record,
            error="stt_failed",
        )

    _maybe_unload_stt(transcriber, unload=unload_now)

    if not transcript:
        _maybe_unload_stt(transcriber, unload=defer_unload)
        reply = plain_error_reply("empty_transcript")
        speaker.speak(reply)
        _voice_audit(audit, "transcript_error", error="empty_transcript")
        return ListenResult(
            transcript="",
            command=None,
            record=record,
            error="empty_transcript",
        )

    _voice_audit(audit, "transcript_received", transcript=transcript)
    try:
        result = handle_command(
            transcript,
            brain=brain,
            speaker=speaker,
            google=google,
            memory=memory,
            spotify=spotify,
            media=media,
            windows=windows,
            apps=apps,
            connectivity=connectivity,
            long_tasks=long_tasks,
            confirmer=confirmer,
            long_task_threshold_s=long_task_threshold_s,
            audit=audit,
        )
    finally:
        _maybe_unload_stt(transcriber, unload=defer_unload)
    return ListenResult(transcript=transcript, command=result, record=record)


def _voice_audit(audit, event: str, **details) -> None:
    if audit is None:
        return
    try:
        audit.log(event, **details)
    except Exception:
        pass
