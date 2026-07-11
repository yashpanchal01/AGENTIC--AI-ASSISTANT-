"""Drive overlay states around the existing voice + handle_command path.

Seam: lifecycle helpers take an Overlay presenter and update it at each stage.
Assertions go through FakeOverlay.states — not paint internals.

Live UI uses short dwells so HEARD / SPEAKING paint at least once (worker
threads can otherwise skip straight to the next state before the 16 ms timer).
Pass heard_dwell_s=0 / speaking_min_s=0 in unit tests for speed.
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
from jarvis.voice import ListenResult, _maybe_unload_stt

if TYPE_CHECKING:
    from jarvis.connectivity import Connectivity

# Long enough for Aurora's ~16 ms paint timer to show the chrome once.
DEFAULT_HEARD_DWELL_S = 0.40
DEFAULT_SPEAKING_MIN_S = 0.30


def _dwell(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


class SpeakingSpeaker:
    """Speaker wrapper that flips the overlay to SPEAKING for speak() + min dwell."""

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
        self._overlay.set_state(
            OverlayState.SPEAKING,
            transcript=self._transcript or None,
        )
        t0 = time.monotonic()
        self._inner.speak(text)
        remaining = self._speaking_min_s - (time.monotonic() - t0)
        _dwell(remaining)


def handle_command_with_overlay(
    transcript_text: str,
    *,
    brain: Brain,
    speaker: Speaker,
    overlay: Overlay,
    google=None,
    connectivity: Connectivity | None = None,
    heard_dwell_s: float = DEFAULT_HEARD_DWELL_S,
    speaking_min_s: float = DEFAULT_SPEAKING_MIN_S,
) -> CommandResult:
    """Run handle_command while showing heard → working → speaking → rest.

    Always returns to REST in ``finally`` so failures never freeze the overlay.
    """
    text = (transcript_text or "").strip()
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
        return handle_command(
            text,
            brain=brain,
            speaker=wrapped,
            google=google,
            connectivity=connectivity,
        )
    finally:
        overlay.set_state(OverlayState.REST, transcript=text)


def listen_and_handle_with_overlay(
    *,
    recorder: MicRecorder,
    transcriber: Transcriber,
    brain: Brain,
    speaker: Speaker,
    overlay: Overlay,
    google=None,
    connectivity: Connectivity | None = None,
    unload_stt_after: bool = False,
    heard_dwell_s: float = DEFAULT_HEARD_DWELL_S,
    speaking_min_s: float = DEFAULT_SPEAKING_MIN_S,
) -> ListenResult:
    """Full voice cycle: armed while recording, then heard → working → speaking → rest.

    ARMED is only held while the mic is recording. After silence ends we move to
    WORKING during STT so the pill never claims the mic is hot during Whisper.

    Local failures are spoken in plain language; overlay always ends in REST.
    """
    overlay.set_state(OverlayState.ARMED)
    rest_owned_by_handler = False
    try:
        record = recorder.record_until_silence()
        if record.audio.size == 0 or not record.heard_speech:
            reply = plain_error_reply("no_speech")
            wrapped = SpeakingSpeaker(
                speaker, overlay, speaking_min_s=speaking_min_s
            )
            wrapped.speak(reply)
            return ListenResult(
                transcript="",
                command=None,
                record=record,
                error="no_speech",
            )

        # Mic is no longer hot — show working while STT runs.
        overlay.set_state(OverlayState.WORKING)

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
            return ListenResult(
                transcript="",
                command=None,
                record=record,
                error="stt_failed",
            )

        _maybe_unload_stt(transcriber, unload=unload_stt_after)

        if not transcript:
            reply = plain_error_reply("empty_transcript")
            wrapped = SpeakingSpeaker(
                speaker, overlay, speaking_min_s=speaking_min_s
            )
            wrapped.speak(reply)
            return ListenResult(
                transcript="",
                command=None,
                record=record,
                error="empty_transcript",
            )

        rest_owned_by_handler = True
        result = handle_command_with_overlay(
            transcript,
            brain=brain,
            speaker=speaker,
            overlay=overlay,
            google=google,
            connectivity=connectivity,
            heard_dwell_s=heard_dwell_s,
            speaking_min_s=speaking_min_s,
        )
        return ListenResult(transcript=transcript, command=result, record=record)
    finally:
        if not rest_owned_by_handler:
            overlay.set_state(OverlayState.REST)
