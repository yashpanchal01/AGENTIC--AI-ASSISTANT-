"""Recording speaker for tests — no audio hardware."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeSpeaker:
    spoken: list[str] = field(default_factory=list)

    def speak(self, text: str) -> None:
        self.spoken.append(text)
