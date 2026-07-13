"""Reflex humility: decline a domain reflex when the utterance is conversational
rather than a clean imperative command, so :mod:`jarvis.core` falls through to the
brain (which has real file/OS tools and can actually find the thing).

Mirrors the conservative bias of :mod:`jarvis.compound`: stay with the fast reflex
when the command is imperative-and-clean, and defer ONLY on a clear conversational
shape or a butchered/garbage extracted query. The live failure that motivated this:

    "i wanna watch dhurandar movie, check in downloads."

The media reflex over-matched on "watch" + "downloads", butchered the query to the
garbage "i wanna dhurandar check", then confidently failed instead of deferring to a
brain that would trivially find the file.

Two independent signals (either one defers):

1. A leading conversational filler ("i wanna", "can you", "please find me", "let's",
   …) — the utterance is phrased as chat, not a terse command.
2. A garbage extracted query — after the reflex stripped command chrome, the leftover
   query still contains words that never belong to a real title/app name ("i",
   "wanna", "check", "movie", …), or nothing survived. That means the extraction
   mangled the utterance and the reflex should not act on the wreckage.

Both are deliberately narrow so canonical commands ("play dhurandar", "play dhurandar
from downloads", "open brave") stay reflex-fast.
"""

from __future__ import annotations

import re

__all__ = [
    "has_conversational_lead",
    "query_looks_garbage",
    "should_defer_to_brain",
]

# Leading filler that marks a request phrased as conversation, not a command.
_CONVERSATIONAL_LEAD = re.compile(
    r"^\s*(?:jarvis[,\s]+)?(?:hey[,\s]+)?"
    r"(?:"
    r"i\s+wanna|i\s+want\s+to|i\s+wanna\b|i\s+wanted\s+to|"
    r"i'?d\s+like|i\s+would\s+like|i\s+need\s+to|i\s+need|"
    r"can\s+you|could\s+you|would\s+you|will\s+you|"
    r"please\s+find\s+me|please\s+could\s+you|please\s+can\s+you|"
    r"let'?s|do\s+you\s+mind"
    r")\b",
    re.I,
)

# Words that never belong to a clean media title or app name. If the reflex's own
# query extraction leaves any of these behind, it mangled the utterance — defer.
_GARBAGE_TOKENS = frozenset(
    {
        "i",
        "wanna",
        "want",
        "wanted",
        "gonna",
        "gotta",
        "check",
        "u",
        "ur",
        "pls",
        "plz",
        "lemme",
        "gimme",
        # Command/domain nouns+verbs that extraction is supposed to have removed;
        # their survival means the strip failed.
        "movie",
        "film",
        "video",
        "watch",
        "play",
        "open",
        "please",
    }
)

_WORD = re.compile(r"[a-z0-9']+")


def has_conversational_lead(text: str) -> bool:
    """True when *text* opens with conversational filler (chat, not a command)."""
    return bool(_CONVERSATIONAL_LEAD.match(text or ""))


def query_looks_garbage(query: str) -> bool:
    """True when an extracted title/name query is empty or carries leftover chrome.

    Conservative: a query is "garbage" only if nothing survived extraction, or a
    leftover token is in :data:`_GARBAGE_TOKENS` (words that are never part of a
    real title/app name). A clean "dhurandar" / "Project Hail Mary" is never
    garbage.
    """
    toks = _WORD.findall((query or "").lower())
    if not toks:
        return True
    return any(t in _GARBAGE_TOKENS for t in toks)


def should_defer_to_brain(text: str, query: str) -> bool:
    """Reflex should hand off to the brain: conversational lead OR garbage query."""
    return has_conversational_lead(text) or query_looks_garbage(query)
