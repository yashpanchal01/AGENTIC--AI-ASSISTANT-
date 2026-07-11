"""Aurora-style native overlay (issue 05)."""

from jarvis.overlay.base import Overlay
from jarvis.overlay.fake import FakeOverlay, OverlayEvent
from jarvis.overlay.lifecycle import (
    handle_command_with_overlay,
    listen_and_handle_with_overlay,
)
from jarvis.overlay.states import ACTIVE_STATES, STATE_TITLE, OverlayState

__all__ = [
    "ACTIVE_STATES",
    "STATE_TITLE",
    "FakeOverlay",
    "Overlay",
    "OverlayEvent",
    "OverlayState",
    "handle_command_with_overlay",
    "listen_and_handle_with_overlay",
]


def load_aurora():
    """Lazy import of the Qt widget (keeps headless installs free of PySide6)."""
    from jarvis.overlay.aurora import AuroraOverlay, shoot_overlay_states

    return AuroraOverlay, shoot_overlay_states
