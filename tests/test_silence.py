"""SilenceTracker ends capture after trailing quiet, not on lead silence alone."""

from __future__ import annotations

import numpy as np

from jarvis.audio.silence import Phase, SilenceConfig, SilenceTracker


def _tone(n: int, amp: float = 0.2) -> np.ndarray:
    # Simple non-zero signal so RMS is predictable.
    return np.full(n, amp, dtype=np.float32)


def _quiet(n: int) -> np.ndarray:
    return np.zeros(n, dtype=np.float32)


def test_lead_silence_does_not_finish_early() -> None:
    cfg = SilenceConfig(
        sample_rate=16_000,
        silence_duration_s=0.5,
        max_lead_silence_s=5.0,
        max_record_s=30.0,
    )
    t = SilenceTracker(cfg)
    # 1 s of quiet at the start — still waiting for speech.
    for _ in range(10):
        t.feed(_quiet(1600))
    assert t.phase is Phase.WAITING
    assert not t.done


def test_speech_then_silence_ends_recording() -> None:
    cfg = SilenceConfig(
        sample_rate=16_000,
        speech_rms=0.05,
        silence_rms=0.02,
        silence_duration_s=0.5,
        min_speech_s=0.2,
        max_record_s=30.0,
    )
    t = SilenceTracker(cfg)
    # 0.4 s speech
    t.feed(_tone(6400, amp=0.2))
    assert t.phase is Phase.SPEAKING
    # 0.3 s silence — not enough yet
    t.feed(_quiet(4800))
    assert t.phase is Phase.SPEAKING
    # another 0.3 s silence → past 0.5 s
    t.feed(_quiet(4800))
    assert t.phase is Phase.DONE


def test_max_record_forces_done() -> None:
    cfg = SilenceConfig(
        sample_rate=16_000,
        max_record_s=1.0,
        max_lead_silence_s=30.0,
        silence_duration_s=5.0,
    )
    t = SilenceTracker(cfg)
    t.feed(_tone(16_000, amp=0.2))  # 1.0 s of continuous speech
    assert t.done


def test_max_lead_silence_with_no_speech() -> None:
    cfg = SilenceConfig(
        sample_rate=16_000,
        max_lead_silence_s=0.5,
        max_record_s=30.0,
    )
    t = SilenceTracker(cfg)
    t.feed(_quiet(8000))  # 0.5 s
    assert t.done
    assert not t.heard_speech or t._samples_speech == 0
