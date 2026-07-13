"""Headless data model for the MK.I SPINE overlay (issue 18).

Separates *what to draw* (this module) from *how to paint it*
(:mod:`jarvis.overlay.spine`). Bus/lifecycle events update a plain object here;
the Qt widget renders from it. This module imports **no** Qt, so the
event -> surface mapping is unit-testable headless with no display.

Mapping (issue 18):

===========================  ==============================================
SPINE surface                Bus event
===========================  ==============================================
step ledger                  StepStarted / StepFinished / StepFailed
thought ticker               TokenTick
brain readout                BrainSelected
fault state                  Fault / StepFailed
commit ring                  ConfirmRequested (until the confirm resolves)
green success pulse          TaskCompleted(ok=True)
mic privacy-shutter          ListeningChanged (closed while not listening)
===========================  ==============================================

Lifecycle base state / transcript / voice level arrive through
:meth:`SpineSurface.apply_state` (the ``Overlay`` protocol path).

All handlers tolerate malformed / out-of-order events without raising: bus
subscribers are already exception-isolated (issue 12), but the face of JARVIS
must never block or crash the command pipeline, so we guard here too.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from enum import Enum

from jarvis.events import (
    BrainSelected,
    ConfirmRequested,
    Fault,
    ListeningChanged,
    StateChanged,
    StepFailed,
    StepFinished,
    StepStarted,
    TaskCompleted,
    TokenTick,
)
from jarvis.overlay.states import OverlayState


class SpineVisual(str, Enum):
    """Prototype's 5 plate states + a CONFIRM accent for the ask-first gate."""

    ARMED = "armed"
    HEARD = "heard"
    WORKING = "working"
    SPEAKING = "speaking"
    CONFIRM = "confirm"
    FAULT = "fault"


# Production lifecycle state -> prototype visual (REST hides the plate).
STATE_TO_VISUAL: dict[OverlayState, SpineVisual | None] = {
    OverlayState.REST: None,
    OverlayState.ARMED: SpineVisual.ARMED,
    OverlayState.HEARD: SpineVisual.HEARD,
    OverlayState.WORKING: SpineVisual.WORKING,
    OverlayState.SPEAKING: SpineVisual.SPEAKING,
    OverlayState.CONFIRM: SpineVisual.CONFIRM,
}

# Brain provider id -> short readout label.
BRAIN_DISPLAY: dict[str, str] = {
    "claude": "CLAUDE",
    "grok": "GROK",
    "fake": "FAKE",
}

# Keep the ledger bounded so a very long session never grows without limit.
MAX_LEDGER = 8


@dataclass
class SpineStep:
    """One step in the ledger. ``status`` in {active, done, failed}."""

    name: str
    detail: str = ""
    step_id: str | None = None
    status: str = "active"
    started_at: float = 0.0
    elapsed: float | None = None
    error: str = ""

    @property
    def label(self) -> str:
        if self.detail:
            return f"{self.name}: {self.detail}"
        return self.name


@dataclass(frozen=True)
class SpineSnapshot:
    """Immutable read-only view handed to the painter each frame."""

    state: OverlayState
    visual: SpineVisual | None
    transcript: str
    level: float
    brain: str
    steps: tuple[SpineStep, ...]
    fault_latched: bool
    fault_text: str
    fault_events: int
    commit_ring: bool
    commit_prompt: str
    mic_muted: bool
    token_chars: int
    token_ticks: int
    last_token_text: str
    success_pulses: int
    revision: int

    @property
    def active(self) -> bool:
        return self.visual is not None


class SpineSurface:
    """Thread-safe surface state updated by event handlers, read by the widget.

    Handlers may be called from the bus/worker thread; the Qt widget marshals
    them onto the UI thread, but the internal lock keeps direct (test) callers
    safe too. Nothing here touches Qt.
    """

    def __init__(self, *, clock=time.monotonic) -> None:
        self._lock = threading.RLock()
        self._clock = clock
        self.state: OverlayState = OverlayState.REST
        self.visual: SpineVisual | None = None
        self.transcript: str = ""
        self.level: float = 0.0
        self.brain: str = ""
        self.steps: list[SpineStep] = []
        self._by_key: dict[str, int] = {}
        self.fault_latched: bool = False
        self.fault_text: str = ""
        self.fault_events: int = 0
        self.commit_ring: bool = False
        self.commit_prompt: str = ""
        # Mic privacy-shutter: True while the front door is NOT listening
        # (resident paused). Real state, not a decorative animation.
        self.mic_muted: bool = False
        # Thought ticker (real token activity feeds the odometer / rate).
        self.token_chars: int = 0
        self.token_ticks: int = 0
        self.last_token_text: str = ""
        self.last_token_at: float = 0.0
        # Green success pulse: a counter the widget converts to a timed pulse.
        self.success_pulses: int = 0
        # Bumps on every mutation so the widget can cheaply detect change.
        self.revision: int = 0

    # -- reads -----------------------------------------------------------------

    def snapshot(self) -> SpineSnapshot:
        with self._lock:
            return SpineSnapshot(
                state=self.state,
                visual=self.visual,
                transcript=self.transcript,
                level=self.level,
                brain=self.brain,
                steps=tuple(replace(s) for s in self.steps[-MAX_LEDGER:]),
                fault_latched=self.fault_latched,
                fault_text=self.fault_text,
                fault_events=self.fault_events,
                commit_ring=self.commit_ring,
                commit_prompt=self.commit_prompt,
                mic_muted=self.mic_muted,
                token_chars=self.token_chars,
                token_ticks=self.token_ticks,
                last_token_text=self.last_token_text,
                success_pulses=self.success_pulses,
                revision=self.revision,
            )

    # -- lifecycle (Overlay protocol path) ------------------------------------

    def apply_state(
        self,
        state: OverlayState,
        *,
        transcript: str | None = None,
        level: float | None = None,
    ) -> None:
        """Base state / transcript / voice level from ``Overlay.set_state``."""
        with self._lock:
            try:
                prev = self.state
                self.state = state
                if transcript is not None:
                    self.transcript = str(transcript)
                if level is not None:
                    self.level = float(level)
                self.visual = STATE_TO_VISUAL.get(state, None)
                # A new command turn clears the previous ledger + fault latch.
                if state is OverlayState.HEARD and prev is not OverlayState.HEARD:
                    self._begin_turn()
                # Commit ring tracks the CONFIRM gate; any non-CONFIRM state
                # (the confirm resolving) clears it.
                if state is OverlayState.CONFIRM:
                    self.commit_ring = True
                else:
                    self.commit_ring = False
            except Exception:  # noqa: BLE001 — never break the pipeline
                pass
            finally:
                self._touch()

    def _begin_turn(self) -> None:
        self.fault_latched = False
        self.fault_text = ""
        self.steps = []
        self._by_key = {}
        self.token_chars = 0
        self.token_ticks = 0
        self.last_token_text = ""
        self.commit_ring = False

    # -- rich bus events -------------------------------------------------------

    def handle_event(self, event: object) -> None:
        """Route one bus event to its surface. Never raises."""
        try:
            if isinstance(event, StepStarted):
                self._step_started(event)
            elif isinstance(event, StepFinished):
                self._resolve_step(event, "done")
            elif isinstance(event, StepFailed):
                self._step_failed(event)
            elif isinstance(event, TokenTick):
                self._token_tick(event)
            elif isinstance(event, BrainSelected):
                self._brain_selected(event)
            elif isinstance(event, ConfirmRequested):
                self._confirm_requested(event)
            elif isinstance(event, Fault):
                self._fault(event)
            elif isinstance(event, TaskCompleted):
                self._task_completed(event)
            elif isinstance(event, ListeningChanged):
                self._listening_changed(event)
            # StateChanged is delivered via apply_state (attach_overlay path).
        except Exception:  # noqa: BLE001 — subscriber isolation, belt & suspenders
            pass

    def _key(self, event: object) -> str:
        sid = getattr(event, "step_id", None)
        if sid:
            return f"id:{sid}"
        name = str(getattr(event, "name", "") or "")
        detail = str(getattr(event, "detail", "") or "")
        return f"nm:{name}|{detail}"

    def _step_started(self, event: object) -> None:
        with self._lock:
            key = self._key(event)
            idx = self._by_key.get(key)
            if idx is not None and 0 <= idx < len(self.steps):
                self.steps[idx].status = "active"
                self.steps[idx].started_at = self._clock()
            else:
                self.steps.append(
                    SpineStep(
                        name=str(getattr(event, "name", "") or ""),
                        detail=str(getattr(event, "detail", "") or ""),
                        step_id=getattr(event, "step_id", None),
                        status="active",
                        started_at=self._clock(),
                    )
                )
                self._by_key[key] = len(self.steps) - 1
            self._touch()

    def _resolve_step(self, event: object, status: str, error: str = "") -> None:
        with self._lock:
            key = self._key(event)
            idx = self._by_key.get(key)
            now = self._clock()
            if idx is None or not (0 <= idx < len(self.steps)):
                # Out-of-order finish/fail before its start — record it anyway.
                step = SpineStep(
                    name=str(getattr(event, "name", "") or ""),
                    detail=str(getattr(event, "detail", "") or ""),
                    step_id=getattr(event, "step_id", None),
                    status=status,
                    started_at=now,
                    error=error,
                )
                self.steps.append(step)
                self._by_key[key] = len(self.steps) - 1
            else:
                step = self.steps[idx]
                step.status = status
                if step.started_at:
                    step.elapsed = max(0.0, now - step.started_at)
                if error:
                    step.error = error
            self._touch()

    def _step_failed(self, event: object) -> None:
        err = str(getattr(event, "error", "") or "") or str(
            getattr(event, "detail", "") or ""
        )
        self._resolve_step(event, "failed", err)
        with self._lock:
            self._latch_fault(err or "step failed")

    def _fault(self, event: object) -> None:
        with self._lock:
            err = str(getattr(event, "error", "") or "")
            detail = str(getattr(event, "detail", "") or "")
            self._latch_fault(err or detail or "fault")

    def _latch_fault(self, text: str) -> None:
        self.fault_latched = True
        self.fault_text = text
        self.visual = SpineVisual.FAULT
        self.fault_events += 1
        self._touch()

    def _token_tick(self, event: object) -> None:
        with self._lock:
            text = str(getattr(event, "text", "") or "")
            self.token_chars += len(text)
            self.token_ticks += 1
            self.last_token_text = text
            self.last_token_at = self._clock()
            self._touch()

    def _brain_selected(self, event: object) -> None:
        with self._lock:
            prov = str(getattr(event, "provider", "") or "").strip().lower()
            self.brain = BRAIN_DISPLAY.get(prov, prov.upper() or "—")
            self._touch()

    def _confirm_requested(self, event: object) -> None:
        with self._lock:
            self.commit_ring = True
            self.commit_prompt = str(
                getattr(event, "proposed_action", "")
                or getattr(event, "prompt", "")
                or ""
            )
            self._touch()

    def _listening_changed(self, event: object) -> None:
        with self._lock:
            listening = bool(getattr(event, "listening", True))
            self.mic_muted = not listening
            self._touch()

    def _task_completed(self, event: object) -> None:
        with self._lock:
            ok = bool(getattr(event, "ok", True))
            if ok:
                self.success_pulses += 1
            # A finished turn resolves any still-pending confirm ring.
            self.commit_ring = False
            self._touch()

    def _touch(self) -> None:
        self.revision += 1


class SpineSubscriber:
    """Feeds bus events into a :class:`SpineSurface`.

    ``StateChanged`` is intentionally ignored here — it reaches the surface via
    the standard ``attach_overlay`` -> ``set_state`` -> ``apply_state`` path, so
    handling it again would double-apply.
    """

    def __init__(self, surface: SpineSurface) -> None:
        self._surface = surface

    def __call__(self, event: object) -> None:
        if isinstance(event, StateChanged):
            return
        self._surface.handle_event(event)


__all__ = [
    "BRAIN_DISPLAY",
    "MAX_LEDGER",
    "STATE_TO_VISUAL",
    "SpineSnapshot",
    "SpineStep",
    "SpineSubscriber",
    "SpineSurface",
    "SpineVisual",
]
