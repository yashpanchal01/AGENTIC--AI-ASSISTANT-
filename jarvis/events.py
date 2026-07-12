"""Typed in-process event bus (issue 12).

One tiny pub/sub seam so the overlay, the audit log, and future surfaces
(tool bridge issue 15, SPINE overlay issue 18) all observe the same stream:
publishers emit typed events; subscribers attach without the pipeline knowing
who is listening.

Contract
--------
- Pure in-process: no sockets, no queues, no dispatcher threads.
- ``publish`` runs subscribers synchronously on the *caller's* thread, in
  subscription order. Subscribers therefore keep the existing thread contract
  (AuroraOverlay already marshals snapshots to the UI thread itself).
- A raising subscriber is isolated — it can never crash command handling or
  starve the other subscribers.
- The bus lock is never held during dispatch, so a subscriber may subscribe,
  unsubscribe, or publish reentrantly without deadlock.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Type-only: a runtime import would cycle via jarvis.overlay.__init__ →
    # lifecycle → core → brain → stream_json → events.
    from jarvis.overlay.states import OverlayState

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StateChanged:
    """Overlay lifecycle state change (mirrors Overlay.set_state args exactly)."""

    state: OverlayState
    transcript: str | None = None
    level: float | None = None


@dataclass(frozen=True)
class TranscriptPartial:
    """Interim STT text while the user is still speaking."""

    text: str


@dataclass(frozen=True)
class TranscriptFinal:
    """Final STT transcript for one command."""

    text: str


@dataclass(frozen=True)
class StepStarted:
    """The brain started one tool step (live, during the call)."""

    name: str
    detail: str = ""
    step_id: str | None = None


@dataclass(frozen=True)
class StepFinished:
    """One tool step returned a result."""

    name: str
    detail: str = ""
    step_id: str | None = None


@dataclass(frozen=True)
class StepFailed:
    """One tool step errored or was denied."""

    name: str
    detail: str = ""
    step_id: str | None = None
    error: str = ""


@dataclass(frozen=True)
class TokenTick:
    """A chunk of assistant text arrived (stream-json text-block granularity)."""

    text: str = ""


@dataclass(frozen=True)
class BrainSelected:
    """Which brain provider will answer ("claude" | "grok" | "fake")."""

    provider: str


@dataclass(frozen=True)
class ConfirmRequested:
    """Ask-first gate armed: the proposed action awaits a yes/no."""

    proposed_action: str = ""
    prompt: str = ""


@dataclass(frozen=True)
class Fault:
    """A spoken-failure boundary was hit (plain-language error already chosen)."""

    error: str
    detail: str = ""


@dataclass(frozen=True)
class TaskCompleted:
    """A brain turn finished (stream-json ``result`` event)."""

    reply: str = ""
    ok: bool = True
    error: str | None = None


@dataclass(frozen=True)
class AuditRecord:
    """One audit-log record riding the bus (name + JSON-able details).

    Audit records are richer than the fixed event vocabulary (command_received,
    command_handled, task_* …) so they keep their own generic envelope; the
    :class:`jarvis.audit.AuditSubscriber` writes them out byte-identically.
    """

    name: str
    details: dict[str, Any] = field(default_factory=dict)


Subscriber = Callable[[object], None]


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------


class EventBus:
    """Thread-safe synchronous pub/sub for the typed events above."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # (token, handler) pairs — tokens make duplicate handlers individually
        # removable.
        self._subscribers: tuple[tuple[int, Subscriber], ...] = ()
        self._next_token = 1

    def subscribe(self, handler: Subscriber) -> Callable[[], None]:
        """Attach *handler* to every published event. Returns an unsubscribe.

        The same callable may be subscribed more than once; each subscription
        gets its own unsubscribe. Unsubscribe is idempotent.
        """
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._subscribers = (*self._subscribers, (token, handler))

        def unsubscribe() -> None:
            with self._lock:
                self._subscribers = tuple(
                    (t, h) for (t, h) in self._subscribers if t != token
                )

        return unsubscribe

    def publish(self, event: object) -> None:
        """Deliver *event* to all subscribers in subscription order.

        Runs on the caller's thread. Exceptions from one subscriber are
        swallowed so a broken listener can never break command handling or
        the remaining subscribers.
        """
        with self._lock:
            subscribers = self._subscribers
        for _token, handler in subscribers:
            try:
                handler(event)
            except Exception:  # noqa: BLE001 — subscriber isolation by contract
                pass


__all__ = [
    "AuditRecord",
    "BrainSelected",
    "ConfirmRequested",
    "EventBus",
    "Fault",
    "StateChanged",
    "StepFailed",
    "StepFinished",
    "StepStarted",
    "Subscriber",
    "TaskCompleted",
    "TokenTick",
    "TranscriptFinal",
    "TranscriptPartial",
]
