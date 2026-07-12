"""Bus-driven overlay seam (issue 12).

The pipeline no longer owns a direct line to the face of JARVIS: it holds a
:class:`BusOverlay`, whose ``set_state`` publishes a typed
:class:`~jarvis.events.StateChanged` on the event bus. The real overlay
(Aurora, or FakeOverlay in tests) becomes **one subscriber among many** via
:func:`attach_overlay`, receiving the exact same ``set_state`` calls in the
exact same order — byte-for-byte identical behavior, but now the tool bridge
(issue 15) and the SPINE overlay (issue 18) can watch the same stream.

The ask-first confirm channel (``take_confirm_decision`` / ``wait_confirm``)
returns values, which a one-way bus cannot model, so those calls delegate
straight to the wrapped overlay. ``arm_confirm`` additionally publishes
:class:`~jarvis.events.ConfirmRequested` for observers.
"""

from __future__ import annotations

from typing import Any, Callable

from jarvis.events import ConfirmRequested, EventBus, StateChanged
from jarvis.overlay.base import Overlay
from jarvis.overlay.states import OverlayState


class OverlaySubscriber:
    """Maps ``StateChanged`` events back onto the Overlay protocol."""

    def __init__(self, overlay: Overlay) -> None:
        self._overlay = overlay

    def __call__(self, event: object) -> None:
        if isinstance(event, StateChanged):
            self._overlay.set_state(
                event.state,
                transcript=event.transcript,
                level=event.level,
            )


def attach_overlay(bus: EventBus, overlay: Overlay) -> Callable[[], None]:
    """Subscribe *overlay* to *bus* state events. Returns the unsubscribe."""
    return bus.subscribe(OverlaySubscriber(overlay))


class BusOverlay:
    """Overlay-shaped front: ``set_state`` publishes; everything else delegates.

    Handed to the pipeline in place of the concrete overlay. Attribute reads
    (``state``, ``transcript``, ``confirm_armed``) and the bidirectional
    confirm channel pass through to the wrapped overlay so duck-typed callers
    (SpeakingSpeaker, confirmers) observe zero change.
    """

    def __init__(self, bus: EventBus, inner: Overlay) -> None:
        self._bus = bus
        self._inner = inner

    def set_state(
        self,
        state: OverlayState,
        *,
        transcript: str | None = None,
        level: float | None = None,
    ) -> None:
        self._bus.publish(
            StateChanged(state=state, transcript=transcript, level=level)
        )

    def close(self) -> None:
        self._inner.close()

    def arm_confirm(self) -> None:
        proposed = str(getattr(self._inner, "transcript", "") or "")
        self._bus.publish(ConfirmRequested(proposed_action=proposed))
        arm = getattr(self._inner, "arm_confirm", None)
        if callable(arm):
            arm()

    def __getattr__(self, name: str) -> Any:
        # Transparent proxy for the confirm channel and state attributes.
        return getattr(self._inner, name)


__all__ = ["BusOverlay", "OverlaySubscriber", "attach_overlay"]
