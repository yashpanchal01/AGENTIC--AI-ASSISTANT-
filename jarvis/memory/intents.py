"""Classify memory voice utterances (remember / recall / forget / unrelated)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class MemoryIntentKind(Enum):
    UNRELATED = auto()
    REMEMBER = auto()  # store a fact as a markdown note
    RECALL = auto()  # retrieve fact(s); empty text → list everything
    FORGET = auto()  # user correction: delete matching note(s)


@dataclass(frozen=True)
class MemoryIntent:
    kind: MemoryIntentKind
    text: str = ""  # fact to store, or recall/forget query


_REMEMBER = tuple(
    re.compile(p, re.I)
    for p in (
        r"^(?:please\s+)?remember(?:\s+that)?\s+(?P<text>.+)$",
        r"^(?:please\s+)?(?:make|take)\s+a\s+note(?:\s+that|\s+of)?\s+(?P<text>.+)$",
        r"^note\s+that\s+(?P<text>.+)$",
        r"^don'?t\s+forget(?:\s+that)?\s+(?P<text>.+)$",
    )
)

_RECALL = tuple(
    re.compile(p, re.I)
    for p in (
        r"^what\s+do\s+you\s+remember(?:\s+about\s+(?P<text>.+))?$",
        r"^what\s+did\s+i\s+(?:tell|ask)\s+you(?:\s+to\s+remember)?"
        r"(?:\s+about\s+(?P<text>.+))?$",
        r"^do\s+you\s+remember\s+(?:anything\s+about\s+)?(?P<text>.+)$",
        r"^what(?:'s|\s+is)\s+in\s+your\s+memory$",
        r"^what\s+have\s+i\s+asked\s+you\s+to\s+remember$",
        r"^list\s+(?:your\s+)?memory(?:\s+notes)?$",
    )
)

_FORGET = tuple(
    re.compile(p, re.I)
    for p in (
        r"^forget\s+(?:that\s+|about\s+|what\s+i\s+said\s+about\s+)?(?P<text>.+)$",
    )
)


def classify(utterance: str) -> MemoryIntent:
    """Match an utterance to a memory intent; UNRELATED falls through to others."""
    text = (utterance or "").strip().rstrip("?!.").strip()
    if not text:
        return MemoryIntent(MemoryIntentKind.UNRELATED)
    for kind, patterns in (
        (MemoryIntentKind.REMEMBER, _REMEMBER),
        (MemoryIntentKind.RECALL, _RECALL),
        (MemoryIntentKind.FORGET, _FORGET),
    ):
        for pattern in patterns:
            m = pattern.match(text)
            if m:
                captured = (m.groupdict().get("text") or "").strip().rstrip("?!.")
                return MemoryIntent(kind, captured)
    return MemoryIntent(MemoryIntentKind.UNRELATED)
