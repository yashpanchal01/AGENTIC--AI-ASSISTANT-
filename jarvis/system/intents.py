"""Classify system-control utterances: screen brightness + latest-capture.

Two everyday verbs (issue 16):

* Brightness — absolute set ("set brightness to 50", "dim brightness to zero"
  → 0, "brightness to max" → 100) and relative step ("turn the brightness up",
  "dim the screen" with no number → step down).
* Latest capture — "open the last screen recording" → newest file, by mtime, in
  the configured capture folders.

Everything else is ``UNRELATED`` (the handler returns None so the command falls
through to the other slices / the brain).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto

# Default relative step for "turn brightness up/down" with no explicit amount.
STEP_PERCENT = 20


class SystemIntentKind(Enum):
    UNRELATED = auto()
    BRIGHTNESS_SET = auto()  # absolute percent (level)
    BRIGHTNESS_STEP = auto()  # relative +/- (delta)
    LATEST_CAPTURE = auto()  # open newest file in capture folders


@dataclass(frozen=True)
class SystemIntent:
    kind: SystemIntentKind
    level: int | None = None  # BRIGHTNESS_SET target, 0..100
    delta: int | None = None  # BRIGHTNESS_STEP signed amount
    category: str = "screen recording"  # LATEST_CAPTURE description


# --- brightness ------------------------------------------------------------

_BRIGHTNESS = re.compile(r"\bbright(?:ness)?\b", re.I)
# "dim / brighten the screen" also counts as a brightness command.
_SCREEN_DIM = re.compile(
    r"\b(?:dim|darken|brighten)\b.*\b(?:screen|display|monitor)\b"
    r"|\b(?:screen|display|monitor)\b.*\b(?:dim(?:mer)?|darker|brighter)\b",
    re.I,
)

# These only run once a brightness context is confirmed, so a bare "up"/"down"
# reliably means the brightness direction ("turn the brightness up").
_STEP_DOWN = re.compile(
    r"\b(?:dim|darken|lower|decrease|reduce|drop|down)\b", re.I
)
_STEP_UP = re.compile(
    r"\b(?:brighten|raise|increase|boost|up)\b", re.I
)

# Word forms for an absolute level.
_WORD_LEVEL: dict[str, int] = {
    "zero": 0,
    "off": 0,
    "min": 0,
    "minimum": 0,
    "lowest": 0,
    "darkest": 0,
    "half": 50,
    "halfway": 50,
    "max": 100,
    "maximum": 100,
    "full": 100,
    "highest": 100,
    "brightest": 100,
}
_WORD_LEVEL_RE = re.compile(
    r"\b(zero|off|min|minimum|lowest|darkest|half|halfway|max|maximum|full|"
    r"highest|brightest)\b",
    re.I,
)
_NUM_LEVEL_RE = re.compile(r"\b(\d{1,3})\s*(?:%|percent|per\s*cent)?\b", re.I)
# "to N" / "at N" / "N percent" strongly implies an absolute target.
_ABS_CUE = re.compile(r"\b(?:to|at|=)\b|\d\s*(?:%|percent)", re.I)


def _parse_level(text: str) -> int | None:
    m = _WORD_LEVEL_RE.search(text)
    if m:
        return _WORD_LEVEL[m.group(1).lower()]
    m = _NUM_LEVEL_RE.search(text)
    if m:
        return max(0, min(100, int(m.group(1))))
    return None


# --- latest capture --------------------------------------------------------

_RECENT = r"(?:last|latest|newest|most[\s-]recent|recent|just\s+captured|" \
    r"we\s+just|i\s+just)"
_CAPTURE_NOUN = r"(?:screen[\s-]?recording|screen[\s-]?capture|screencast|" \
    r"recording|capture|clip|screen\s+grab)"

_LATEST_CAPTURE = re.compile(
    r"\b(?:open|play|show|pull\s+up|bring\s+up|watch)\b.*"
    r"(?:"
    rf"\b{_RECENT}\b.*\b{_CAPTURE_NOUN}\b"
    rf"|\b{_CAPTURE_NOUN}\b.*\b{_RECENT}\b"
    r")",
    re.I | re.S,
)


def classify(utterance: str) -> SystemIntent:
    text = (utterance or "").strip()
    if not text:
        return SystemIntent(SystemIntentKind.UNRELATED)

    # Latest capture first — it never mentions brightness, so order is safe.
    if _LATEST_CAPTURE.search(text):
        return SystemIntent(SystemIntentKind.LATEST_CAPTURE)

    is_brightness = bool(_BRIGHTNESS.search(text) or _SCREEN_DIM.search(text))
    if is_brightness:
        level = _parse_level(text)
        going_down = bool(_STEP_DOWN.search(text))
        going_up = bool(_STEP_UP.search(text))
        # An explicit number/word with an absolute cue (or no direction verb)
        # means "set to that value". "dim to zero" → SET 0, not a step.
        if level is not None and (_ABS_CUE.search(text) or not (going_up or going_down)):
            return SystemIntent(SystemIntentKind.BRIGHTNESS_SET, level=level)
        if going_up:
            delta = level if level is not None else STEP_PERCENT
            return SystemIntent(SystemIntentKind.BRIGHTNESS_STEP, delta=abs(delta))
        if going_down:
            delta = level if level is not None else STEP_PERCENT
            return SystemIntent(SystemIntentKind.BRIGHTNESS_STEP, delta=-abs(delta))
        if level is not None:
            return SystemIntent(SystemIntentKind.BRIGHTNESS_SET, level=level)
        # "brightness" mentioned but no level/direction — not actionable here.
        return SystemIntent(SystemIntentKind.UNRELATED)

    return SystemIntent(SystemIntentKind.UNRELATED)
