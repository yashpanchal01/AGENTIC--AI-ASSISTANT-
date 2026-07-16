"""In-session working memory: a bounded dialogue thread every tier appends to.

Issue 20. Distinct from markdown long-term memory (issue 07): this is the
last few *exchanges* of the current sitting, so follow-ups have a referent
("pause that", "no, the other one"). The Claude/Grok brains already resume
their own session (``--resume``), so they remember their OWN turns — the gap
is reflex/offline-handled turns the brain never saw. :meth:`digest` renders
exactly those (nothing more) as a terse block the core prepends to the next
brain command. Token budget matters: hard caps on turn count and line length.

Ownership: created by the resident loop / ``handle_command`` caller and
threaded through ``handle_command`` (like ``audit``); appends happen at the
same seam as audit logging so there is no second scatter of call sites.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

# Ring size: enough for "that thing from a minute ago", small enough that a
# worst-case digest stays well under a few hundred tokens.
DEFAULT_MAX_TURNS = 8
# Silence gap after which the next turn is a fresh conversation (seconds).
DEFAULT_STALE_AFTER_S = 10 * 60.0
# Per-line truncation for the digest (utterance / reply), characters.
_TEXT_MAX = 80

DIGEST_HEADER = "[Recent exchanges JARVIS handled locally (you did not see these):"
DIGEST_FOOTER = "The user now says:]"


def _trunc(text: str) -> str:
    text = " ".join((text or "").split())
    if len(text) > _TEXT_MAX:
        return text[: _TEXT_MAX - 1] + "…"
    return text


@dataclass(frozen=True)
class DialogueTurn:
    """One exchange: what the user said and which tier answered."""

    utterance: str
    tier: str  # "reflex" | "offline" | "brain"
    reply: str
    ok: bool
    timestamp: float
    # True only when the brain process actually received this turn (its own
    # resumed session covers it). Denied/declined/unreachable brain-tier turns
    # never reached a CLI process, so they stay digest-visible.
    seen_by_brain: bool = False


@dataclass
class DialogueThread:
    """Ring buffer of the last few turns, shared by all tiers.

    ``now`` is injectable for tests (monotonic seconds).
    """

    max_turns: int = DEFAULT_MAX_TURNS
    stale_after_s: float = DEFAULT_STALE_AFTER_S
    now: Callable[[], float] = time.monotonic
    _turns: deque[DialogueTurn] = field(default_factory=deque, init=False)

    @property
    def turns(self) -> tuple[DialogueTurn, ...]:
        return tuple(self._turns)

    def append(
        self,
        utterance: str,
        *,
        tier: str,
        reply: str,
        ok: bool,
        seen_by_brain: bool | None = None,
    ) -> None:
        """Record one exchange; turn N+max evicts turn 1 (bounded)."""
        if seen_by_brain is None:
            seen_by_brain = tier == "brain"
        self._turns.append(
            DialogueTurn(
                utterance=(utterance or "").strip(),
                tier=tier,
                reply=(reply or "").strip(),
                ok=ok,
                timestamp=self.now(),
                seen_by_brain=seen_by_brain,
            )
        )
        while len(self._turns) > self.max_turns:
            self._turns.popleft()

    def clear(self) -> None:
        self._turns.clear()

    def is_stale(self) -> bool:
        """True when the gap since the last turn exceeds the threshold."""
        if not self._turns:
            return False
        return (self.now() - self._turns[-1].timestamp) > self.stale_after_s

    def reset_if_stale(self) -> bool:
        """Clear the thread after a long silence. Returns True if cleared.

        The caller must also ``brain.reset_session()`` — a fresh conversation,
        like a person walking back into the room.
        """
        if self.is_stale():
            self.clear()
            return True
        return False

    def unseen_turns(self) -> tuple[DialogueTurn, ...]:
        """Turns since the brain last actually received a prompt."""
        pending: list[DialogueTurn] = []
        for turn in reversed(self._turns):
            if turn.seen_by_brain:
                break
            pending.append(turn)
        return tuple(reversed(pending))

    def digest(self) -> str:
        """Terse "recent exchanges" block for the brain — only unseen turns.

        Empty string when the brain is already up to date (consecutive brain
        turns never re-inject context; ``--resume`` covers the brain's own).
        """
        pending = self.unseen_turns()
        if not pending:
            return ""
        lines = [DIGEST_HEADER]
        for t in pending:
            status = "ok" if t.ok else "failed"
            lines.append(
                f'- user: "{_trunc(t.utterance)}" -> {t.tier}: '
                f'"{_trunc(t.reply)}" ({status})'
            )
        lines.append(DIGEST_FOOTER)
        return "\n".join(lines)

    def compose_brain_command(self, text: str) -> str:
        """Prepend the digest (if any) to a brain-bound command."""
        briefing = self.digest()
        if not briefing:
            return text
        return f"{briefing}\n{text}"


__all__ = [
    "DEFAULT_MAX_TURNS",
    "DEFAULT_STALE_AFTER_S",
    "DialogueThread",
    "DialogueTurn",
]
