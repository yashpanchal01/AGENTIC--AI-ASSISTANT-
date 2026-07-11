"""Tunable hotwords / dictionary for proper-noun transcription quality.

Copied pattern from LocalFlow (read-only reference): seed list + user-editable
``dictionary.txt`` + narrow post-hoc CORRECTIONS for observed mishears.
This is *not* a polish model — raw whisper text still goes to the brain after
optional regex term fixes.
"""

from __future__ import annotations

import re
from pathlib import Path

# JARVIS-oriented seed list (LocalFlow names + assistant-specific terms).
DEFAULT_DICTIONARY: tuple[str, ...] = (
    "Jarvis",
    "Claude Code",
    "Claude",
    "Whisper",
    "Piper",
    "GitHub",
    "Python",
    "VS Code",
    "API",
    "Anthropic",
    "Gmail",
    "Spotify",
    "Notepad",
)

# Observed mishears → canonical form (narrow, unambiguous patterns only).
CORRECTIONS: dict[str, str] = {
    r"\b(?:blood|cloud|clod|clot|claw|clawed|clogged|clout) ?"
    r"(?:cold|code|coat|called|cord)\b": "Claude Code",
    r"\b(?:broadcourt|claudecote|claudecode)\b": "Claude Code",
    r"\bget ?hub\b": "GitHub",
    r"\bjarv(?:i|e)s\b": "Jarvis",
}


def default_dictionary_path() -> Path:
    """Project-root dictionary.txt (next to pyproject / package parent)."""
    return Path(__file__).resolve().parents[2] / "dictionary.txt"


def load_dictionary(path: Path | None = None) -> list[str]:
    """Return dictionary terms; seed the file on first run if missing."""
    dict_path = path or default_dictionary_path()
    try:
        if not dict_path.exists():
            dict_path.parent.mkdir(parents=True, exist_ok=True)
            header = (
                "# JARVIS dictionary — one word or name per line.\n"
                "# Whisper is biased toward these (hotwords / initial_prompt).\n"
                "# Lines starting with '#' are ignored.\n"
                "# Edits apply on the next listen.\n\n"
            )
            dict_path.write_text(
                header + "\n".join(DEFAULT_DICTIONARY) + "\n",
                encoding="utf-8",
            )
        terms: list[str] = []
        for line in dict_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                terms.append(line)
        return terms or list(DEFAULT_DICTIONARY)
    except OSError:
        return list(DEFAULT_DICTIONARY)


def hotwords_string(path: Path | None = None) -> str:
    """Space-joined hotwords for faster-whisper ``hotwords`` / ``initial_prompt``."""
    return " ".join(load_dictionary(path))


def fix_terms(text: str) -> str:
    """Apply narrow post-transcription corrections for known proper-noun slips."""
    out = text
    for pat, rep in CORRECTIONS.items():
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    return out
