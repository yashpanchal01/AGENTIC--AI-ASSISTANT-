"""Local wake-word front door (issue 04)."""

from jarvis.wake.base import SAMPLE_RATE, Detection, WakeDetector
from jarvis.wake.fake import FakeWakeDetector, silence_frames
from jarvis.wake.factory import create_wake_detector, try_create_wake_detector
from jarvis.wake.phrases import DEFAULT_WAKE_PHRASES, strip_wake_phrase
from jarvis.wake.pipeline import run_armed_pipeline
from jarvis.wake.session import CycleResult, FrontDoorSession

__all__ = [
    "SAMPLE_RATE",
    "DEFAULT_WAKE_PHRASES",
    "CycleResult",
    "Detection",
    "FakeWakeDetector",
    "FrontDoorSession",
    "WakeDetector",
    "create_wake_detector",
    "run_armed_pipeline",
    "silence_frames",
    "strip_wake_phrase",
    "try_create_wake_detector",
]
