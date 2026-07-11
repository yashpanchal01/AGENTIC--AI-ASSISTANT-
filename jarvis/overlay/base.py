"""Overlay presenter protocol — pipeline drives states without knowing Qt."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from jarvis.overlay.states import OverlayState


@runtime_checkable
class Overlay(Protocol):
    """Public seam for the face of JARVIS.

    Implementations must tolerate calls from worker threads. FakeOverlay
    writes attributes inline; AuroraOverlay marshals snapshots to the UI
    thread and never calls Qt paint/show APIs inside set_state.
    """

    def set_state(
        self,
        state: OverlayState,
        *,
        transcript: str | None = None,
        level: float | None = None,
    ) -> None:
        """Switch lifecycle state. Pass transcript to update the heard text."""
        ...

    def close(self) -> None:
        """Release UI resources (no-op for fakes)."""
        ...
