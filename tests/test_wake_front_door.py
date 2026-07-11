"""Wake word + hotkey front door (issue 04) — fakes only, no mic/hardware."""

from __future__ import annotations

import itertools
from unittest import mock

import numpy as np

from jarvis.audio.capture import MicRecorder
from jarvis.audio.silence import SilenceConfig
from jarvis.brain.fake import FakeBrain
from jarvis.overlay.fake import FakeOverlay
from jarvis.overlay.states import OverlayState
from jarvis.stt.fake import FakeTranscriber
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import Action, BrainTurn
from jarvis.wake.fake import FakeWakeDetector
from jarvis.wake.hotkey import FakeHotkeyController
from jarvis.wake.phrases import is_wake_only, strip_wake_phrase
from jarvis.wake.pipeline import run_armed_pipeline
from jarvis.wake.session import FrontDoorSession


def _speech_quiet(
    *,
    speech_s: float = 0.5,
    silence_s: float = 1.0,
    sr: int = 16_000,
) -> list[np.ndarray]:
    speech = np.full(int(sr * speech_s), 0.2, dtype=np.float32)
    quiet = np.zeros(int(sr * silence_s), dtype=np.float32)
    return [speech, quiet]


def _silence_cfg() -> SilenceConfig:
    return SilenceConfig(silence_duration_s=0.5, min_speech_s=0.2)


# --- phrase stripping (one-breath) ------------------------------------------


def test_strip_wake_phrase_one_breath() -> None:
    assert strip_wake_phrase("Jarvis, open notepad") == "open notepad"
    assert strip_wake_phrase("hey jarvis open chrome") == "open chrome"
    assert strip_wake_phrase("JARVIS open downloads") == "open downloads"
    assert strip_wake_phrase("open notepad") == "open notepad"


def test_strip_wake_only_is_empty() -> None:
    assert strip_wake_phrase("Jarvis") == ""
    assert strip_wake_phrase("hey jarvis") == ""
    assert is_wake_only("Jarvis!")
    assert not is_wake_only("Jarvis open it")


# --- shared pipeline --------------------------------------------------------


def test_wake_fires_full_path_to_brain_and_speaker() -> None:
    brain = FakeBrain(
        script=[
            BrainTurn(reply="Opened Notepad.", actions=(Action("launch_app", "Notepad"),))
        ]
    )
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="Jarvis, open notepad")
    rec = MicRecorder(config=_silence_cfg(), blocks=_speech_quiet())

    outcome = run_armed_pipeline(
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        source="wake",
    )

    assert outcome.ok
    assert outcome.transcript == "open notepad"
    assert outcome.command is not None
    assert outcome.command.reply == "Opened Notepad."
    assert speaker.spoken == ["Opened Notepad."]


def test_hotkey_uses_same_pipeline_entry_point() -> None:
    """Hotkey and wake both call run_armed_pipeline (shared entry)."""
    brain = FakeBrain(script=[BrainTurn(reply="Done.", actions=())])
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="what time is it")
    rec = MicRecorder(config=_silence_cfg(), blocks=_speech_quiet())

    with mock.patch(
        "jarvis.wake.session.run_armed_pipeline",
        wraps=run_armed_pipeline,
    ) as shared:
        fl = 512
        detector = FakeWakeDetector(fire_after_frames=1)

        def frames():
            return (np.zeros(fl, dtype=np.int16) for _ in range(8))

        session = FrontDoorSession(
            detector=detector,
            recorder=rec,
            transcriber=stt,
            brain=brain,
            speaker=speaker,
            enable_hotkey=True,
            hotkey_controller=FakeHotkeyController(),
            frames_factory=frames,
        )
        # Wake path
        session.run(max_cycles=1)
        assert shared.call_count == 1
        assert shared.call_args.kwargs["source"] == "wake"

        # Hotkey path — re-arm recorder/stt
        stt2 = FakeTranscriber(text="open chrome")
        rec2 = MicRecorder(config=_silence_cfg(), blocks=_speech_quiet())
        hk = FakeHotkeyController()
        # Frames never fire wake; hotkey does.
        detector2 = FakeWakeDetector(detections=[None] * 1000)

        def silent_frames():
            # Yield empties so wait loop can poll hotkey_event.
            def gen():
                for i in range(200):
                    if i == 5:
                        hk.fire()
                    yield np.zeros(0, dtype=np.int16)

            return gen()

        session2 = FrontDoorSession(
            detector=detector2,
            recorder=rec2,
            transcriber=stt2,
            brain=brain,
            speaker=speaker,
            enable_hotkey=True,
            hotkey_controller=hk,
            frames_factory=silent_frames,
        )
        with mock.patch(
            "jarvis.wake.session.run_armed_pipeline",
            wraps=run_armed_pipeline,
        ) as shared2:
            results = session2.run(max_cycles=1)
            assert len(results) == 1
            assert results[0].source == "hotkey"
            assert shared2.call_count == 1
            assert shared2.call_args.kwargs["source"] == "hotkey"
            assert results[0].outcome.transcript == "open chrome"


def test_wake_required_again_for_second_command() -> None:
    brain = FakeBrain(
        script=[
            BrainTurn(reply="First done.", actions=()),
            BrainTurn(reply="Second done.", actions=()),
        ]
    )
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text=["open notepad", "open chrome"])
    rec = MicRecorder(
        config=_silence_cfg(),
        block_sessions=[_speech_quiet(), _speech_quiet()],
    )
    fl = 512
    # Fire on first frame of each wait; reset() re-arms fire_after_frames.
    detector = FakeWakeDetector(fire_after_frames=1)

    def frames():
        return (np.zeros(fl, dtype=np.int16) for _ in range(4))

    session = FrontDoorSession(
        detector=detector,
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        enable_hotkey=False,
        frames_factory=frames,
    )
    cycles = session.run(max_cycles=2)

    assert len(cycles) == 2
    assert all(c.source == "wake" for c in cycles)
    assert cycles[0].outcome.transcript == "open notepad"
    assert cycles[1].outcome.transcript == "open chrome"
    assert speaker.spoken == ["First done.", "Second done."]
    # Two separate waits → detector processed frames twice at least
    assert detector.process_calls >= 2
    assert detector.reset_calls >= 2


def test_one_breath_strips_wake_and_runs_command() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="OK.", actions=())])
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="hey jarvis open downloads")
    rec = MicRecorder(config=_silence_cfg(), blocks=_speech_quiet())

    outcome = run_armed_pipeline(
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        source="wake",
    )
    assert outcome.ok
    assert outcome.transcript == "open downloads"
    # No two-step acknowledge
    assert "Yes?" not in speaker.spoken
    assert speaker.spoken == ["OK."]


def test_two_step_wake_then_command() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="Launched.", actions=())])
    speaker = FakeSpeaker()
    # First record = wake only; second = command
    stt = FakeTranscriber(text=["Jarvis", "open notepad"])
    rec = MicRecorder(
        config=_silence_cfg(),
        block_sessions=[_speech_quiet(), _speech_quiet()],
    )

    outcome = run_armed_pipeline(
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        source="wake",
        acknowledge_text="Yes?",
    )
    assert outcome.ok
    assert outcome.transcript == "open notepad"
    assert speaker.spoken[0] == "Yes?"
    assert speaker.spoken[1] == "Launched."
    assert len(stt.calls) == 2


def test_hotkey_does_not_strip_incidental_jarvis_in_middle() -> None:
    """Hotkey path should not require wake stripping of full phrase only at start —
    actually strip only applies for source=wake. Hotkey passes transcript as-is.
    """
    brain = FakeBrain(script=[BrainTurn(reply="OK.", actions=())])
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="Jarvis, open notepad")
    rec = MicRecorder(config=_silence_cfg(), blocks=_speech_quiet())

    outcome = run_armed_pipeline(
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        source="hotkey",
    )
    # Hotkey keeps full transcript (no strip)
    assert outcome.transcript == "Jarvis, open notepad"


def test_front_door_drives_overlay_lifecycle() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="Done.", actions=())])
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text="open notepad")
    rec = MicRecorder(config=_silence_cfg(), blocks=_speech_quiet())
    overlay = FakeOverlay()
    fl = 512
    detector = FakeWakeDetector(fire_after_frames=1)

    def frames():
        return (np.zeros(fl, dtype=np.int16) for _ in range(4))

    session = FrontDoorSession(
        detector=detector,
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        overlay=overlay,
        enable_hotkey=False,
        frames_factory=frames,
    )
    cycles = session.run(max_cycles=1)
    assert cycles[0].outcome.ok
    states = overlay.states
    assert OverlayState.ARMED in states
    assert OverlayState.HEARD in states
    assert OverlayState.WORKING in states
    assert OverlayState.SPEAKING in states
    assert states[-1] is OverlayState.REST


def test_run_one_cycle_is_shared_for_wake_and_hotkey() -> None:
    brain = FakeBrain(
        script=[
            BrainTurn(reply="A.", actions=()),
            BrainTurn(reply="B.", actions=()),
        ]
    )
    speaker = FakeSpeaker()
    stt = FakeTranscriber(text=["cmd a", "cmd b"])
    rec = MicRecorder(
        config=_silence_cfg(),
        block_sessions=[_speech_quiet(), _speech_quiet()],
    )
    session = FrontDoorSession(
        detector=FakeWakeDetector(),
        recorder=rec,
        transcriber=stt,
        brain=brain,
        speaker=speaker,
        enable_hotkey=False,
    )
    # Direct shared entry (bypassing wait) — same method for both sources.
    r1 = session.run_one_cycle("wake")
    r2 = session.run_one_cycle("hotkey")
    assert r1.transcript == "cmd a"
    assert r2.transcript == "cmd b"
    assert speaker.spoken == ["A.", "B."]
