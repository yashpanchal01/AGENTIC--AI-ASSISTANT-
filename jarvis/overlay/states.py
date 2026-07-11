"""Canonical overlay lifecycle states (PRD / design: armed → heard → working → speaking)."""

from __future__ import annotations

from enum import Enum


class OverlayState(str, Enum):
    """Visible JARVIS face states. REST hides the pill."""

    REST = "rest"
    ARMED = "armed"
    HEARD = "heard"
    WORKING = "working"
    SPEAKING = "speaking"
    # Ask-first gate (issue 06): preview the exact proposed action; yes/no.
    CONFIRM = "confirm"


# User-facing titles drawn on the pill (kept short for the Mono chrome).
STATE_TITLE: dict[OverlayState, str] = {
    OverlayState.REST: "",
    OverlayState.ARMED: "Armed",
    OverlayState.HEARD: "Heard",
    OverlayState.WORKING: "Working…",
    OverlayState.SPEAKING: "Speaking",
    OverlayState.CONFIRM: "Confirm?",
}

# States that keep the overlay visible (vs faded out at REST).
ACTIVE_STATES: frozenset[OverlayState] = frozenset(
    {
        OverlayState.ARMED,
        OverlayState.HEARD,
        OverlayState.WORKING,
        OverlayState.SPEAKING,
        OverlayState.CONFIRM,
    }
)
