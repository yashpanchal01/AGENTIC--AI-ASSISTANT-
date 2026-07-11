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
    """Captures every set_state call for behavioral assertions."""

    events: list[OverlayEvent] = field(default_factory=list)
    state: OverlayState = OverlayState.REST
    transcript: str = ""
    level: float = 0.0
    closed: bool = False

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
        self.events.append(
            OverlayEvent(state=state, transcript=self.transcript, level=level)
        )

    def close(self) -> None:
        self.closed = True

    @property
    def states(self) -> list[OverlayState]:
        return [e.state for e in self.events]
