"""Front-door session: wake word + hotkey as the only ways into the pipeline.

After each command the session returns to waiting — no open-mic follow-up.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from jarvis.audio.capture import MicRecorder, RecordResult
from jarvis.brain.base import Brain
from jarvis.overlay.base import Overlay
from jarvis.stt.base import Transcriber
from jarvis.tasks import LongTaskService
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


def _empty_listen_result(*, error: str) -> ListenResult:
    return ListenResult(
        transcript="",
        command=None,
        record=RecordResult(
            audio=np.zeros(0, dtype=np.float32),
            sample_rate=16_000,
            duration_s=0.0,
            heard_speech=False,
        ),
        error=error,
    )


@dataclass
class FrontDoorSession:
    """Continuous listen loop until stop() or max_cycles.

    Production: pass a real WakeDetector; frames=None uses the mic.
    Tests: inject FakeWakeDetector + frames iterator and/or FakeHotkeyController.

    Holds a shared :class:`LongTaskService` so wake-word "cancel" aborts an
    in-flight background brain turn (issue 10).
    """

    detector: WakeDetector
    recorder: MicRecorder
    transcriber: Transcriber
    brain: Brain
    speaker: Speaker
    overlay: Overlay | None = None
    google: Any = None
    memory: Any = None
    spotify: Any = None
    media: Any = None
    windows: Any = None
    apps: Any = None
    system: Any = None
    long_tasks: LongTaskService | None = None
    confirmer: Any = None
    wake_phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES
    hotkey: str | None = "ctrl+shift+j"
    enable_hotkey: bool = True
    # Injected frame source (int16 chunks). None → real mic for wake wait.
    frames_factory: Callable[[], Iterator[np.ndarray]] | None = None
    # External hotkey event (tests); if set, pynput is not started.
    hotkey_controller: FakeHotkeyController | None = None
    acknowledge_text: str | None = "Yes?"
    on_cycle: Callable[[CycleResult], None] | None = None
    connectivity: Any = None
    unload_stt_after: bool = False
    # Overlay dwell knobs (defaults match lifecycle; tests pass 0).
    heard_dwell_s: float | None = None
    speaking_min_s: float | None = None
    long_task_threshold_s: float | None = None
    # Issue 11: pause gate + audit trail (optional; tests inject MemoryAuditLog).
    resident: Any = None  # ResidentController | None
    audit: Any = None
    # Issue 20: shared dialogue thread — the resident session owns the working
    # memory so context survives across cycles. None → created lazily.
    dialogue: Any = None  # DialogueThread | None
    # Issue 23: shared event bus so any tier's failed turn faults the overlay.
    bus: Any = None  # EventBus | None

    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _hotkey_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _hotkey_listener: Any = field(default=None, init=False, repr=False)
    cycles: list[CycleResult] = field(default_factory=list, init=False)

    def stop(self) -> None:
        self._stop.set()
        self._hotkey_event.set()  # unblock waiters
        # Align resident stop so wait_while_paused / combined stop exit.
        if self.resident is not None and not getattr(self.resident, "is_stopping", True):
            try:
                self.resident.quit()
            except Exception:
                pass

    def request_hotkey(self) -> None:
        """Simulate / signal push-to-talk (also used by the real HotkeyListener).

        While paused, ignore presses so the hotkey cannot arm a cycle.
        """
        if self._is_paused() or self._should_stop():
            return
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
                        # Ignore hotkey while paused — stay deaf.
                        if self._is_paused():
                            continue
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
        """Block until wake or hotkey. Public for tests.

        When *resident* is present, pause and quit both abort the wait
        (``InterruptedError``) so the mic/detector do not stay open while
        the tray says paused.
        """
        frames = None
        if self.frames_factory is not None:
            frames = self.frames_factory()
        if hasattr(self.detector, "reset"):
            try:
                self.detector.reset()
            except Exception:
                pass
        # Composite stop: session stop OR resident quit OR resident pause.
        stop = self._stop
        if self.resident is not None:
            stop = _CombinedStop(self._stop, self.resident)
        return wait_for_wake(
            self.detector,
            frames=frames,
            hotkey_event=self._hotkey_event if self.enable_hotkey else None,
            stop_event=stop,
        )

    def _is_paused(self) -> bool:
        return self.resident is not None and bool(getattr(self.resident, "is_paused", False))

    def _should_stop(self) -> bool:
        if self._stop.is_set():
            return True
        if self.resident is not None and bool(getattr(self.resident, "is_stopping", False)):
            return True
        return False

    def run_one_cycle(self, source: TriggerSource) -> ListenResult:
        """Run the shared armed pipeline once (wake and hotkey both land here)."""
        # TOCTOU: re-check pause/stop at pipeline entry.
        if self._is_paused() or self._should_stop():
            if self.audit is not None:
                try:
                    self.audit.log("cycle_aborted_paused", source=source)
                except Exception:
                    pass
            return _empty_listen_result(error="paused")

        # Lazily create a shared long-task service so cancel works across cycles.
        if self.long_tasks is None:
            thresh = (
                self.long_task_threshold_s
                if self.long_task_threshold_s is not None
                else None
            )
            if thresh is not None:
                self.long_tasks = LongTaskService(
                    threshold_s=thresh, audit=self.audit
                )
            else:
                self.long_tasks = LongTaskService(audit=self.audit)
        # Lazily create the shared dialogue thread (issue 20) so follow-ups
        # across cycles have a referent even when the caller passed none.
        if self.dialogue is None:
            from jarvis.dialogue import DialogueThread

            self.dialogue = DialogueThread()
        kwargs: dict[str, Any] = {
            "recorder": self.recorder,
            "transcriber": self.transcriber,
            "brain": self.brain,
            "speaker": self.speaker,
            "source": source,
            "overlay": self.overlay,
            "google": self.google,
            "memory": self.memory,
            "spotify": self.spotify,
            "media": self.media,
            "windows": self.windows,
            "apps": self.apps,
            "system": self.system,
            "long_tasks": self.long_tasks,
            "confirmer": self.confirmer,
            "wake_phrases": self.wake_phrases,
            "acknowledge_text": self.acknowledge_text,
            "connectivity": self.connectivity,
            "unload_stt_after": self.unload_stt_after,
            "long_task_threshold_s": self.long_task_threshold_s,
            "audit": self.audit,
            "dialogue": self.dialogue,
            "bus": self.bus,
        }
        if self.heard_dwell_s is not None:
            kwargs["heard_dwell_s"] = self.heard_dwell_s
        if self.speaking_min_s is not None:
            kwargs["speaking_min_s"] = self.speaking_min_s
        return run_armed_pipeline(**kwargs)

    def run(self, *, max_cycles: int | None = None) -> list[CycleResult]:
        """Main front-door loop. Returns completed cycle results.

        When *resident* is paused, wake/hotkey waits abort and the loop sits
        deaf until resume or quit (mic not held open while paused).
        """
        self._stop.clear()
        warn = self._start_hotkey_backend()
        if warn:
            # Non-fatal: wake-only mode.
            print(f"JARVIS> hotkey disabled: {warn}")

        results: list[CycleResult] = []
        try:
            while not self._should_stop():
                if max_cycles is not None and len(results) >= max_cycles:
                    break
                # While paused, do not arm the detector — sit deaf until resume.
                if self._is_paused():
                    # Drain any hotkey presses so they do not fire on resume.
                    self._hotkey_event.clear()
                    if self.resident is not None:
                        if not self.resident.wait_while_paused(poll_s=0.05):
                            break
                    self._hotkey_event.clear()
                    if self._should_stop():
                        break
                    continue
                try:
                    source, detection = self.wait_for_trigger()
                except InterruptedError:
                    # Pause aborts wait_for_trigger (hard deaf); quit/stop exit.
                    if self._should_stop():
                        break
                    if self._is_paused():
                        self._hotkey_event.clear()
                        continue
                    break
                except LookupError:
                    # Scripted frames exhausted — end cleanly in tests.
                    break

                # Trigger arrived while paused (race): discard — stay deaf.
                if self._is_paused() or self._should_stop():
                    if self.audit is not None:
                        try:
                            self.audit.log(
                                "trigger_ignored_while_paused",
                                source=source,
                            )
                        except Exception:
                            pass
                    continue

                if self.audit is not None:
                    try:
                        self.audit.log("front_door_armed", source=source)
                    except Exception:
                        pass

                outcome = self.run_one_cycle(source)
                # Paused mid-race before pipeline: do not count as a cycle.
                if outcome.error == "paused":
                    continue
                cycle = CycleResult(source=source, detection=detection, outcome=outcome)
                results.append(cycle)
                self.cycles.append(cycle)
                if self.on_cycle is not None:
                    self.on_cycle(cycle)
        finally:
            # Always signal stop so the fake-hotkey poller (and any waiters) exit.
            self._stop.set()
            self._stop_hotkey_backend()
        return results


class _CombinedStop:
    """Event-like object set on session stop, resident quit, or resident pause.

    Pause aborts an in-flight ``wait_for_wake`` so the mic/detector do not stay
    open while the tray reports paused. ``wait()`` polls both sides.
    """

    def __init__(self, session_stop: threading.Event, resident: Any) -> None:
        self._session_stop = session_stop
        self._resident = resident

    def is_set(self) -> bool:
        if self._session_stop.is_set():
            return True
        if bool(getattr(self._resident, "is_stopping", False)):
            return True
        if bool(getattr(self._resident, "is_paused", False)):
            return True
        return False

    def wait(self, timeout: float | None = None) -> bool:
        """Return True if set (stop/quit/pause), False on timeout."""
        if timeout is None:
            while not self.is_set():
                self._session_stop.wait(0.05)
            return True
        deadline = time.monotonic() + max(0.0, timeout)
        while not self.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._session_stop.wait(min(0.05, remaining))
        return True
