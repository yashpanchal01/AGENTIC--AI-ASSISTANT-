"""Front-door session: wake word + hotkey as the only ways into the pipeline.

After each command the session returns to waiting — no open-mic follow-up.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from jarvis.audio.capture import MicRecorder
from jarvis.brain.base import Brain
from jarvis.overlay.base import Overlay
from jarvis.stt.base import Transcriber
from jarvis.tts.base import Speaker
from jarvis.voice import ListenResult
from jarvis.wake.base import Detection, WakeDetector
from jarvis.wake.hotkey import FakeHotkeyController, HotkeyError, HotkeyListener
from jarvis.wake.listen import wait_for_wake
from jarvis.wake.phrases import DEFAULT_WAKE_PHRASES
from jarvis.wake.pipeline import TriggerSource, run_armed_pipeline


@dataclass
class CycleResult:
    source: TriggerSource
    detection: Detection | None
    outcome: ListenResult


@dataclass
class FrontDoorSession:
    """Continuous listen loop until stop() or max_cycles.

    Production: pass a real WakeDetector; frames=None uses the mic.
    Tests: inject FakeWakeDetector + frames iterator and/or FakeHotkeyController.
    """

    detector: WakeDetector
    recorder: MicRecorder
    transcriber: Transcriber
    brain: Brain
    speaker: Speaker
    overlay: Overlay | None = None
    google: Any = None
    wake_phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES
    hotkey: str | None = "ctrl+shift+j"
    enable_hotkey: bool = True
    # Injected frame source (int16 chunks). None → real mic for wake wait.
    frames_factory: Callable[[], Iterator[np.ndarray]] | None = None
    # External hotkey event (tests); if set, pynput is not started.
    hotkey_controller: FakeHotkeyController | None = None
    acknowledge_text: str | None = "Yes?"
    on_cycle: Callable[[CycleResult], None] | None = None

    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _hotkey_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _hotkey_listener: Any = field(default=None, init=False, repr=False)
    cycles: list[CycleResult] = field(default_factory=list, init=False)

    def stop(self) -> None:
        self._stop.set()
        self._hotkey_event.set()  # unblock waiters

    def request_hotkey(self) -> None:
        """Simulate / signal push-to-talk (also used by the real HotkeyListener)."""
        self._hotkey_event.set()

    def _start_hotkey_backend(self) -> str | None:
        """Return a warning string if hotkey could not be enabled."""
        if not self.enable_hotkey or not self.hotkey:
            return None
        if self.hotkey_controller is not None:
            # Bridge fake controller → internal event.
            def _poll_fake() -> None:
                while not self._stop.is_set():
                    if self.hotkey_controller.event.wait(0.05):
                        self.hotkey_controller.clear()
                        self._hotkey_event.set()

            t = threading.Thread(target=_poll_fake, daemon=True)
            t.start()
            return None
        try:
            listener = HotkeyListener(self.hotkey, on_press=self.request_hotkey)
            listener.start()
            self._hotkey_listener = listener
            return None
        except HotkeyError as exc:
            return str(exc)

    def _stop_hotkey_backend(self) -> None:
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
            self._hotkey_listener = None

    def wait_for_trigger(self) -> tuple[TriggerSource, Detection | None]:
        """Block until wake or hotkey. Public for tests."""
        frames = None
        if self.frames_factory is not None:
            frames = self.frames_factory()
        if hasattr(self.detector, "reset"):
            try:
                self.detector.reset()
            except Exception:
                pass
        return wait_for_wake(
            self.detector,
            frames=frames,
            hotkey_event=self._hotkey_event if self.enable_hotkey else None,
            stop_event=self._stop,
        )

    def run_one_cycle(self, source: TriggerSource) -> ListenResult:
        """Run the shared armed pipeline once (wake and hotkey both land here)."""
        return run_armed_pipeline(
            recorder=self.recorder,
            transcriber=self.transcriber,
            brain=self.brain,
            speaker=self.speaker,
            source=source,
            overlay=self.overlay,
            google=self.google,
            wake_phrases=self.wake_phrases,
            acknowledge_text=self.acknowledge_text,
        )

    def run(self, *, max_cycles: int | None = None) -> list[CycleResult]:
        """Main front-door loop. Returns completed cycle results."""
        self._stop.clear()
        warn = self._start_hotkey_backend()
        if warn:
            # Non-fatal: wake-only mode.
            print(f"JARVIS> hotkey disabled: {warn}")

        results: list[CycleResult] = []
        try:
            while not self._stop.is_set():
                if max_cycles is not None and len(results) >= max_cycles:
                    break
                try:
                    source, detection = self.wait_for_trigger()
                except InterruptedError:
                    break
                except LookupError:
                    # Scripted frames exhausted — end cleanly in tests.
                    break

                outcome = self.run_one_cycle(source)
                cycle = CycleResult(source=source, detection=detection, outcome=outcome)
                results.append(cycle)
                self.cycles.append(cycle)
                if self.on_cycle is not None:
                    self.on_cycle(cycle)
        finally:
            self._stop_hotkey_backend()
        return results
