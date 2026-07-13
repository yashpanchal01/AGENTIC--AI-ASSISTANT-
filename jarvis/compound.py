"""Detect genuinely compound / multi-step utterances (issue 17 gap).

A leading regex reflex (apps / media / windows / spotify) will happily capture a
multi-step command and half-execute it — e.g. the apps ``_OPEN`` reflex reads
"open spotify and play the next music", resolves the "spotify" prefix, and just
launches Spotify, dropping "play next". :func:`is_compound_command` lets the core
DECLINE such utterances at the reflex layer so they fall through to the brain +
MCP tool bridge (issue 15), which executes the whole task.

The detector is deliberately conservative — biased to FALSE (stay with the
single-command reflex) so the everyday "play rock and roll" / "open command and
conquer" style utterances are never stolen from their normal tier. It returns
True only for two unambiguous shapes:

1. A conjunction (" and ", " then ", ", then ", "; ", " & ", " after that ")
   followed by a SECOND imperative action verb starting a new command
   ("… and play the next music" → second verb "play"). A verb immediately
   followed by a back-reference pronoun ("… and play it", "… and open it") is a
   continuation of the same task, not a new action, so it does NOT trigger.
2. A two-window ARRANGEMENT the brain must compose: "side by side",
   "split screen", "next to each other", or an explicit LEFT placement paired
   with an explicit RIGHT placement ("brave left 50%, vs code right").
"""

from __future__ import annotations

import re

__all__ = ["is_compound_command"]

# Conjunctions that can join two independent commands. Spaces are significant:
# " and " never matches inside "command" or "sandwich".
_CONJUNCTIONS: tuple[str, ...] = (
    " and ",
    " then ",
    ", then ",
    "; ",
    " & ",
    " after that ",
)

# Imperative action verbs that begin a genuine second command.
_VERB = (
    r"(?:play|pause|resume|stop|skip|next|previous|open|launch|start|run|close|"
    r"minimi[sz]e|maximi[sz]e|snap|move|put|set|dim|turn|mute|focus|switch|show|"
    r"delete|send)"
)

# Small fillers that may sit between the conjunction and the second verb
# ("… and then play", "… and also open").
_FILLER = r"(?:then|also|now|just|please|go\s+ahead\s+and|maybe)\s+"

# A second command = optional filler, then a verb — but NOT a verb whose only
# object is a back-reference pronoun ("play it", "open them"): that is the SAME
# task continued (classic media "find X and play it"), not a new action. Only
# "it"/"them" are excluded — they are always back-references, whereas "this"/
# "that" are usually determiners of a real object ("skip this song").
_SECOND_ACTION = re.compile(
    rf"^(?:{_FILLER})*{_VERB}\b(?!\s+(?:it|them)\b)",
    re.IGNORECASE,
)

# --- window-arrangement shape ---------------------------------------------

# Phrases that inherently describe two windows laid out together.
_ARRANGE_TWO = re.compile(
    r"\bside[\s-]?by[\s-]?side\b"
    r"|\bsplit[\s-]?screen\b"
    r"|\bnext\s+to\s+each\s+other\b",
    re.IGNORECASE,
)

# An explicit LEFT / RIGHT placement. A single window is snapped to ONE side, so
# only a LEFT *and* a RIGHT placement together imply a two-window layout.
_PLACE_LEFT = re.compile(
    r"\bleft\s+half\b|\bleft\s+side\b|\bleft\s+50\b|\bleft\s*50\s*%"
    r"|\b(?:on|to)\s+the\s+left\b",
    re.IGNORECASE,
)
_PLACE_RIGHT = re.compile(
    r"\bright\s+half\b|\bright\s+side\b|\bright\s+50\b|\bright\s*50\s*%"
    r"|\b(?:on|to)\s+the\s+right\b"
    # bare trailing "right" ("…, vs code right") — only paired with an explicit
    # left placement does this count, so it can't fire on a single snap.
    r"|\bright\b(?=\s*$|\s*[,.])",
    re.IGNORECASE,
)


def _has_second_action(text: str) -> bool:
    low = text.lower()
    for conj in _CONJUNCTIONS:
        start = 0
        while True:
            pos = low.find(conj, start)
            if pos == -1:
                break
            remainder = text[pos + len(conj):].lstrip()
            if _SECOND_ACTION.match(remainder):
                return True
            start = pos + len(conj)
    return False


def _is_two_window_layout(text: str) -> bool:
    if _ARRANGE_TWO.search(text):
        return True
    return bool(_PLACE_LEFT.search(text) and _PLACE_RIGHT.search(text))


def is_compound_command(text: str) -> bool:
    """True only for genuinely multi-step utterances (see module docstring).

    Biased to False: an ambiguous utterance stays with its single-command
    reflex. Only a clear second action verb after a conjunction, or a two-window
    arrangement phrase, returns True.
    """
    t = (text or "").strip()
    if not t:
        return False
    return _has_second_action(t) or _is_two_window_layout(t)
