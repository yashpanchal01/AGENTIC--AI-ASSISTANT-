"""Drive overlay states around the existing voice + handle_command path.

Seam: lifecycle helpers take an Overlay presenter and update it at each stage.
Assertions go through FakeOverlay.states — not paint internals.

Live UI uses short dwells so HEARD / SPEAKING paint at least once (worker
threads can otherwise skip straight to the next state before the 16 ms timer).
Pass heard_dwell_s=0 / speaking_min_s=0 in unit tests for speed.

Long tasks (issue 10): when handle_command returns ``backgrounded=True``, the
overlay stays in WORKING (after the spoken "On it." ack) until the task
service announces completion/failure or cancel and returns it to REST.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from jarvis.audio.capture import MicRecorder
from jarvis.brain.base import Brain
from jarvis.core import CommandResult, handle_command
from jarvis.overlay.base import Overlay
from jarvis.overlay.states import OverlayState
from jarvis.plain_replies import plain_error_reply
from jarvis.stt.base import Transcriber
from jarvis.tts.base import Speaker
from jarvis.voice import ListenResult, _maybe_unload_stt, confirmer_may_use_stt

if TYPE_CHECKING:
    from jarvis.connectivity import Connectivity
    from jarvis.tasks import LongTaskService

# Long enough for Aurora's ~16 ms paint timer to show the chrome once.
DEFAULT_HEARD_DWELL_S = 0.40
DEFAULT_SPEAKING_MIN_S = 0.30


def _dwell(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _overlay_voice_audit(audit, event: str, **details) -> None:
    """Mirror jarvis.voice._voice_audit — local STT failures must leave a trail."""
    if audit is None:
        return
    try:
        audit.log(event, **details)
    except Exception:
        pass


def _overlay_confirm_armed(overlay: Overlay) -> bool:
    """True while the ask-first gate is accepting Yes/No (armed, not just CONFIRM paint)."""
    armed = getattr(overlay, "confirm_armed", None)
    if armed is not None:
        return bool(armed)
    return bool(getattr(overlay, "_confirm_armed", False))


class SpeakingSpeaker:
    """Speaker wrapper that flips the overlay to SPEAKING for speak() + min dwell.

    While the overlay is in CONFIRM **and** confirm is still armed (ask-first
    wait), speak does **not** switch to SPEAKING — Yes/No hit targets must stay
    visible. After disarm / leave CONFIRM, follow-up TTS uses SPEAKING normally.
    """

    def __init__(
        self,
        inner: Speaker,
        overlay: Overlay,
        *,
        transcript: str = "",
        speaking_min_s: float = DEFAULT_SPEAKING_MIN_S,
    ) -> None:
        self._inner = inner
        self._overlay = overlay
        self._transcript = transcript
        self._speaking_min_s = speaking_min_s

    def speak(self, text: str) -> None:
        current = getattr(self._overlay, "state", None)
        preserve_confirm = (
            current is OverlayState.CONFIRM and _overlay_confirm_armed(self._overlay)
        )
        confirm_preview = (
            getattr(self._overlay, "transcript", None) if preserve_confirm else None
        )
        if not preserve_confirm:
            self._overlay.set_state(
                OverlayState.SPEAKING,
                transcript=self._transcript or None,
            )
        t0 = time.monotonic()
        self._inner.speak(text)
        remaining = self._speaking_min_s - (time.monotonic() - t0)
        _dwell(remaining)
        if preserve_confirm and _overlay_confirm_armed(self._overlay):
            # Re-assert CONFIRM so late SPEAKING frames cannot steal the chrome.
            self._overlay.set_state(
                OverlayState.CONFIRM,
                transcript=confirm_preview or self._transcript or None,
            )


def handle_command_with_overlay(
    transcript_text: str,
    *,
    brain: Brain,
    speaker: Speaker,
    overlay: Overlay,
    google=None,
    memory=None,
    spotify=None,
    media=None,
    windows=None,
    apps=None,
    system=None,
    connectivity: Connectivity | None = None,
    long_tasks: LongTaskService | None = None,
    confirmer=None,
    heard_dwell_s: float = DEFAULT_HEARD_DWELL_S,
    speaking_min_s: float = DEFAULT_SPEAKING_MIN_S,
    long_task_threshold_s: float | None = None,
    audit=None,
) -> CommandResult:
    """Run handle_command while showing heard → working → speaking → rest.

    Returns to REST in ``finally`` unless a long task was backgrounded — then
    the overlay stays WORKING until the task service finishes or is cancelled.

    When the brain needs ask-first confirmation, ``handle_command`` switches
    the overlay to CONFIRM (action preview) before speaking the prompt.
    """
    text = (transcript_text or "").strip()
    # Stay WORKING for backgrounded long tasks and for busy refusals
    # (STILL_WORKING) so a concurrent command cannot drop the chrome to REST.
    keep_working = False
    try:
        overlay.set_state(OverlayState.HEARD, transcript=text)
        _dwell(heard_dwell_s)
        overlay.set_state(OverlayState.WORKING, transcript=text)
        wrapped = SpeakingSpeaker(
            speaker,
            overlay,
            transcript=text,
            speaking_min_s=speaking_min_s,
        )
        result = handle_command(
            text,
            brain=brain,
            speaker=wrapped,
            google=google,
            memory=memory,
            spotify=spotify,
            media=media,
            windows=windows,
            apps=apps,
            system=system,
            connectivity=connectivity,
            long_tasks=long_tasks,
            overlay=overlay,
            confirmer=confirmer,
            speaking_min_s=speaking_min_s,
            long_task_threshold_s=long_task_threshold_s,
            audit=audit,
        )
        keep_working = bool(result.backgrounded) or result.error == "busy"
        if keep_working:
            # Ack / busy reply was spoken (SPEAKING); resume WORKING.
            overlay.set_state(OverlayState.WORKING, transcript=text)
        return result
    finally:
        if not keep_working:
            overlay.set_state(OverlayState.REST, transcript=text)


def listen_and_handle_with_overlay(
    *,
    recorder: MicRecorder,
    transcriber: Transcriber,
    brain: Brain,
    speaker: Speaker,
    overlay: Overlay,
    google=None,
    memory=None,
    spotify=None,
    media=None,
    windows=None,
    apps=None,
    system=None,
    connectivity: Connectivity | None = None,
    long_tasks: LongTaskService | None = None,
    confirmer=None,
    unload_stt_after: bool = False,
    heard_dwell_s: float = DEFAULT_HEARD_DWELL_S,
    speaking_min_s: float = DEFAULT_SPEAKING_MIN_S,
    long_task_threshold_s: float | None = None,
    audit=None,
) -> ListenResult:
    """Full voice cycle: armed while recording, then heard → working → speaking → rest.

    ARMED is only held while the mic is recording. After silence ends we move to
    WORKING during STT so the pill never claims the mic is hot during Whisper.

    Local failures are spoken in plain language; overlay ends in REST unless a
    long task was backgrounded (stays WORKING).
    """
    # Default voice+click confirmer when not injected (issue 06).
    if confirmer is None:
        from jarvis.confirm import VoiceOrClickConfirmer

        confirmer = VoiceOrClickConfirmer(
            overlay=overlay,
            recorder=recorder,
            transcriber=transcriber,
        )
    # ARMED level drives Aurora bar amplitude ("mic hot").
    overlay.set_state(OverlayState.ARMED, level=0.55)
    rest_owned_by_handler = False
    try:
        record = recorder.record_until_silence()
        if record.audio.size == 0 or not record.heard_speech:
            reply = plain_error_reply("no_speech")
            wrapped = SpeakingSpeaker(
                speaker, overlay, speaking_min_s=speaking_min_s
            )
            wrapped.speak(reply)
            _overlay_voice_audit(audit, "transcript_error", error="no_speech")
            return ListenResult(
                transcript="",
                command=None,
                record=record,
                error="no_speech",
            )

        # Mic is no longer hot — show working while STT runs.
        overlay.set_state(OverlayState.WORKING)

        # Keep Whisper loaded through voice yes/no confirm when needed.
        defer_unload = bool(unload_stt_after and confirmer_may_use_stt(confirmer))
        unload_now = bool(unload_stt_after and not defer_unload)

        try:
            transcript = (
                transcriber.transcribe(record.audio, sample_rate=record.sample_rate)
                or ""
            ).strip()
        except Exception:  # noqa: BLE001 — never freeze overlay on STT crash
            _maybe_unload_stt(transcriber, unload=unload_stt_after)
            reply = plain_error_reply("stt_failed")
            wrapped = SpeakingSpeaker(
                speaker, overlay, speaking_min_s=speaking_min_s
            )
            wrapped.speak(reply)
            _overlay_voice_audit(audit, "transcript_error", error="stt_failed")
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
            wrapped = SpeakingSpeaker(
                speaker, overlay, speaking_min_s=speaking_min_s
            )
            wrapped.speak(reply)
            _overlay_voice_audit(audit, "transcript_error", error="empty_transcript")
            return ListenResult(
                transcript="",
                command=None,
                record=record,
                error="empty_transcript",
            )

        _overlay_voice_audit(audit, "transcript_received", transcript=transcript)
        rest_owned_by_handler = True
        try:
            result = handle_command_with_overlay(
                transcript,
                brain=brain,
                speaker=speaker,
                overlay=overlay,
                google=google,
                memory=memory,
                spotify=spotify,
                media=media,
                windows=windows,
                apps=apps,
                system=system,
                connectivity=connectivity,
                long_tasks=long_tasks,
                confirmer=confirmer,
                heard_dwell_s=heard_dwell_s,
                speaking_min_s=speaking_min_s,
                long_task_threshold_s=long_task_threshold_s,
                audit=audit,
            )
        finally:
            _maybe_unload_stt(transcriber, unload=defer_unload)
        return ListenResult(transcript=transcript, command=result, record=record)
    finally:
        if not rest_owned_by_handler:
            overlay.set_state(OverlayState.REST)
