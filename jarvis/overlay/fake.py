"""Recording overlay for tests — no Qt, no windows."""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.overlay.states import OverlayState


@dataclass(frozen=True)
class OverlayEvent:
    state: OverlayState
    transcript: str
    level: float | None = None


@dataclass
class FakeOverlay:
    """Captures every set_state call for behavioral assertions.

    Confirm click backup (issue 06): preload ``pending_confirm`` (True/False)
    or call ``queue_confirm(yes)``; ``take_confirm_decision`` / ``wait_confirm``
    deliver it to an OverlayClickConfirmer.
    """

    events: list[OverlayEvent] = field(default_factory=list)
    state: OverlayState = OverlayState.REST
    transcript: str = ""
    level: float = 0.0
    closed: bool = False
    # Queued yes/no click decisions for the ask-first gate.
    pending_confirm: bool | None = None
    confirm_armed: bool = False
    confirm_previews: list[str] = field(default_factory=list)

    def set_state(
        self,
        state: OverlayState,
        *,
        transcript: str | None = None,
        level: float | None = None,
    ) -> None:
        if transcript is not None:
            self.transcript = transcript
        if level is not None:
            self.level = level
        self.state = state
        if state is OverlayState.CONFIRM:
            self.confirm_previews.append(self.transcript)
        self.events.append(
            OverlayEvent(state=state, transcript=self.transcript, level=level)
        )

    def close(self) -> None:
        self.closed = True

    @property
    def states(self) -> list[OverlayState]:
        return [e.state for e in self.events]

    # -- Confirm click backup (mirrors AuroraOverlay duck-typed API) ----------

    def arm_confirm(self) -> None:
        self.confirm_armed = True

    def disarm_confirm(self) -> None:
        self.confirm_armed = False

    def queue_confirm(self, yes: bool) -> None:
        """Test helper: queue a click decision for the next take/wait."""
        self.pending_confirm = bool(yes)

    def take_confirm_decision(self) -> bool | None:
        """Non-blocking: return and clear a queued click, if any."""
        decision = self.pending_confirm
        self.pending_confirm = None
        return decision

    def wait_confirm(self, timeout_s: float = 0.0) -> bool | None:
        """Return a queued decision (tests do not block on timeout)."""
        _ = timeout_s
        return self.take_confirm_decision()
