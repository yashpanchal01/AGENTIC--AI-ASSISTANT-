"""Strip leading wake phrases from STT transcripts (one-breath support)."""

from __future__ import annotations

import re

# Longest first so "hey jarvis" wins over bare "jarvis".
DEFAULT_WAKE_PHRASES: tuple[str, ...] = (
    "hey jarvis",
    "okay jarvis",
    "ok jarvis",
    "jarvis",
)


def strip_wake_phrase(
    transcript: str,
    phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES,
) -> str:
    """Remove a leading wake phrase (and optional following comma/pause punct).

    Examples:
      "Jarvis, open notepad"  → "open notepad"
      "hey jarvis open chrome" → "open chrome"
      "Jarvis"                 → ""
      "open notepad"           → "open notepad"  (unchanged)
    """
    text = (transcript or "").strip()
    if not text:
        return ""

    # Prefer longer phrases first.
    ordered = sorted({p.strip().lower() for p in phrases if p.strip()}, key=len, reverse=True)
    lower = text.lower()
    for phrase in ordered:
        if lower == phrase:
            return ""
        # "jarvis," / "jarvis " / "hey jarvis —"
        pattern = rf"^{re.escape(phrase)}[\s,.\-—–:!;?]+"
        m = re.match(pattern, lower)
        if m:
            return text[m.end() :].strip()
        # Exact prefix without separator when next char is end (already handled)
        # or when phrase is whole first word token sequence.
        if lower.startswith(phrase + " "):
            return text[len(phrase) :].strip()
    return text


def is_wake_only(
    transcript: str,
    phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES,
) -> bool:
    """True when the transcript is only the wake word (two-step first half)."""
    return strip_wake_phrase(transcript, phrases) == "" and bool((transcript or "").strip())
