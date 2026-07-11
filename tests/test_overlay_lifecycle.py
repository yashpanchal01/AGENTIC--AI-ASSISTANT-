"""Behavioral tests for overlay state drive (issue 04 / GitHub #4).

Seam: FakeOverlay.states + CommandResult/ListenResult — no Qt, no paint.
Dwells are zero so the suite stays fast; live CLI uses real dwells for paint.
"""

from __future__ import annotations

import numpy as np

from jarvis.audio.capture import MicRecorder
from jarvis.audio.silence import SilenceConfig
from jarvis.brain.fake import FakeBrain
from jarvis.overlay.fake import FakeOverlay
from jarvis.overlay.lifecycle import (
    handle_command_with_overlay,
    listen_and_handle_with_overlay,
)
from jarvis.overlay.states import OverlayState, STATE_TITLE
from jarvis.stt.fake import FakeTranscriber
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import Action, BrainTurn


def test_state_titles_cover_lifecycle() -> None:
    assert STATE_TITLE[OverlayState.ARMED] == "Armed"
    assert STATE_TITLE[OverlayState.HEARD] == "Heard"
    assert "Working" in STATE_TITLE[OverlayState.WORKING]
    assert STATE_TITLE[OverlayState.SPEAKING] == "Speaking"


def test_handle_command_drives_heard_working_speaking_rest() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="Opened Notepad.", actions=(Action("launch_app", "Notepad"),))]
    )
    speaker = FakeSpeaker()
    overlay = FakeOverlay()

    result = handle_command_with_overlay(
        "open notepad",
        brain=brain,
        speaker=speaker,
        overlay=overlay,
        heard_dwell_s=0,
        speaking_min_s=0,
    )

    assert result.ok
    assert result.reply == "Opened Notepad."
    assert speaker.spoken == ["Opened Notepad."]
    states = overlay.states
    assert OverlayState.HEARD in states
    assert OverlayState.WORKING in states
    assert OverlayState.SPEAKING in states
    assert states[-1] is OverlayState.REST
    i_h = states.index(OverlayState.HEARD)
    i_w = states.index(OverlayState.WORKING)
    i_s = states.index(OverlayState.SPEAKING)
    assert i_h < i_w < i_s < len(states) - 1
    heard_events = [e for e in overlay.events if e.state is OverlayState.HEARD]
    assert heard_events[0].transcript == "open notepad"


def test_listen_drives_armed_then_full_lifecycle() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="Done.", actions=())])
    speaker = FakeSpeaker()
    overlay = FakeOverlay()
    stt = FakeTranscriber(text="what time is it")
    sr = 16_000
    speech = np.full(int(sr * 0.5), 0.2, dtype=np.float32)
    quiet = np.zeros(int(sr * 1.0), dtype=np.float32)
    rec = MicRecorder(
        config=SilenceConfig(silence_duration_s=0.5, min_speech_s=0.2),
        blocks=[speech, quiet],
    )

    outcome = listen_and_handle_with_overlay(
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        overlay=overlay,
        heard_dwell_s=0,
        speaking_min_s=0,
    )

    assert outcome.ok
    assert outcome.transcript == "what time is it"
    states = overlay.states
    assert states[0] is OverlayState.ARMED
    # After recording, ARMED ends (WORKING during STT) before HEARD.
    first_working = states.index(OverlayState.WORKING)
    first_heard = states.index(OverlayState.HEARD)
    assert first_working < first_heard
    assert OverlayState.SPEAKING in states
    assert states[-1] is OverlayState.REST
    assert states.count(OverlayState.REST) == 1


def test_listen_no_speech_returns_to_rest_and_speaks() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="nope", actions=())])
    speaker = FakeSpeaker()
    overlay = FakeOverlay()
    stt = FakeTranscriber(text="should not run")
    sr = 16_000
    quiet = [np.zeros(sr, dtype=np.float32)]
    rec = MicRecorder(
        config=SilenceConfig(max_lead_silence_s=0.5, max_record_s=5.0),
        blocks=quiet,
    )

    outcome = listen_and_handle_with_overlay(
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        overlay=overlay,
        heard_dwell_s=0,
        speaking_min_s=0,
    )

    assert not outcome.ok
    assert outcome.error == "no_speech"
    assert speaker.spoken  # plain-language spoken error
    assert OverlayState.ARMED in overlay.states
    assert OverlayState.HEARD not in overlay.states
    assert overlay.states[-1] is OverlayState.REST


def test_listen_empty_transcript_returns_to_rest_without_heard() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="nope", actions=())])
    speaker = FakeSpeaker()
    overlay = FakeOverlay()
    stt = FakeTranscriber(text="")
    sr = 16_000
    speech = np.full(int(sr * 0.5), 0.2, dtype=np.float32)
    quiet = np.zeros(int(sr * 1.0), dtype=np.float32)
    rec = MicRecorder(
        config=SilenceConfig(silence_duration_s=0.5, min_speech_s=0.2),
        blocks=[speech, quiet],
    )

    outcome = listen_and_handle_with_overlay(
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        overlay=overlay,
        heard_dwell_s=0,
        speaking_min_s=0,
    )

    assert not outcome.ok
    assert outcome.error == "empty_transcript"
    assert speaker.spoken
    assert OverlayState.ARMED in overlay.states
    assert OverlayState.WORKING in overlay.states  # STT phase
    assert OverlayState.HEARD not in overlay.states
    assert overlay.states[-1] is OverlayState.REST
