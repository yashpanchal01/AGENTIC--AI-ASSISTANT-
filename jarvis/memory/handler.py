"""Route memory voice intents to the markdown store (issue 07)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from jarvis.confirm import is_secret_request
from jarvis.memory.base import MemoryResult
from jarvis.memory.intents import MemoryIntentKind, classify
from jarvis.memory.store import MemoryStore
from jarvis.types import Action

_SECRET_REFUSAL = (
    "I never store passwords, API keys, or credentials in my memory notes."
)

_MAX_SPOKEN_FACTS = 3
_MAX_LISTED = 5


@dataclass
class MemoryHandlerImpl:
    """Concrete hub: memory intent → markdown store → spoken reply + actions."""

    store: MemoryStore = field(default_factory=MemoryStore)
    # Notes are local files — handle_command may run this while offline.
    works_offline: bool = True

    def try_handle(self, utterance: str) -> MemoryResult | None:
        intent = classify(utterance)
        if intent.kind is MemoryIntentKind.UNRELATED:
            return None
        if intent.kind is MemoryIntentKind.REMEMBER:
            return self._remember(intent.text)
        if intent.kind is MemoryIntentKind.RECALL:
            return self._recall(intent.text)
        return self._forget(intent.text)

    def _remember(self, fact: str) -> MemoryResult:
        if is_secret_request(fact):
            return MemoryResult(reply=_SECRET_REFUSAL, denied=True, ok=True)
        try:
            note = self.store.remember(fact)
        except ValueError:
            # Store-level guard (secrets / empty) — same spoken refusal.
            return MemoryResult(reply=_SECRET_REFUSAL, denied=True, ok=True)
        return MemoryResult(
            reply=f"Got it — I'll remember that {note.fact.rstrip('.')}.",
            actions=(Action(name="remember", detail=note.fact),),
        )

    def _recall(self, query: str) -> MemoryResult:
        if query and is_secret_request(query):
            return MemoryResult(reply=_SECRET_REFUSAL, denied=True, ok=True)
        if not query:
            notes = self.store.notes()
            if not notes:
                return MemoryResult(
                    reply="I don't have any memory notes yet.",
                    actions=(Action(name="recall", detail="all"),),
                )
            shown = notes[:_MAX_LISTED]
            listed = "; ".join(n.summary for n in shown)
            more = len(notes) - len(shown)
            tail = f"; and {more} more." if more > 0 else "."
            plural = "s" if len(notes) != 1 else ""
            return MemoryResult(
                reply=f"I remember {len(notes)} thing{plural}: {listed}{tail}",
                actions=(Action(name="recall", detail="all"),),
            )
        matches = self.store.search(query)
        if not matches:
            return MemoryResult(
                reply=f"I don't have a note about {query}.",
                actions=(Action(name="recall", detail=query),),
            )
        facts = [m.fact.rstrip(".") for m in matches[:_MAX_SPOKEN_FACTS]]
        reply = f"You told me: {facts[0]}."
        for extra in facts[1:]:
            reply += f" Also: {extra}."
        return MemoryResult(
            reply=reply,
            actions=(Action(name="recall", detail=query),),
        )

    def _forget(self, query: str) -> MemoryResult:
        removed = self.store.forget(query)
        if not removed:
            return MemoryResult(
                reply=f"I don't have a note about {query} to forget.",
                actions=(),
            )
        n = len(removed)
        what = removed[0].summary if n == 1 else f"{n} notes about {query}"
        return MemoryResult(
            reply=f"Okay — I've forgotten {what}.",
            actions=tuple(
                Action(name="forget", detail=note.fact) for note in removed
            ),
        )


def build_memory_handler(root: Path | None = None) -> MemoryHandlerImpl:
    """Handler over markdown notes at *root* (default: JARVIS_MEMORY_DIR / ~/.jarvis/memory)."""
    return MemoryHandlerImpl(store=MemoryStore(root))
