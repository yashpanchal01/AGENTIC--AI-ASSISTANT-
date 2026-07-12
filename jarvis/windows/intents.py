"""Classify voice window-management commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Literal

SnapSide = Literal["left", "right"] | None


class WindowIntentKind(Enum):
    UNRELATED = auto()
    FULLSCREEN = auto()
    MAXIMIZE = auto()
    MINIMIZE = auto()
    MINIMIZE_ALL = auto()
    FOCUS = auto()
    CLOSE = auto()
    RESTORE = auto()
    SNAP = auto()


@dataclass(frozen=True)
class WindowIntent:
    kind: WindowIntentKind
    target: str = ""
    snap: SnapSide = None


_MEDIA_PLAY = re.compile(
    r"\b(?:play|watch)\b.+\b(?:from\s+)?(?:downloads?|desktop|documents?)\b"
    r"|\b(?:play|watch)\b.+\b(?:movie|film)\b",
    re.I,
)

_FULLSCREEN = re.compile(
    r"\b(?:go\s+)?full[\s-]?screen\b"
    r"|\benter\s+fullscreen\b"
    r"|\bmake\b.+\bfull[\s-]?screen\b",
    re.I,
)
_MAXIMIZE = re.compile(r"\bmaximize\b|\bmaximise\b", re.I)
_MINIMIZE_ALL = re.compile(
    r"\b(?:minimize|minimise)\s+all(?:\s+windows?)?\b"
    r"|\bminimise\s+everything\b"
    r"|\bminimize\s+everything\b"
    r"|\bshow\s+desktop\b",
    re.I,
)
_MINIMIZE = re.compile(r"\bminimize\b|\bminimise\b", re.I)
_CLOSE = re.compile(r"\bclose\b(?:\s+the)?\s+(?P<t>.+)$", re.I)
_FOCUS = re.compile(
    r"\b(?:focus|switch to|bring up|activate)\b(?:\s+the)?\s+(?P<t>.+)$",
    re.I,
)
_RESTORE = re.compile(r"\brestore\b(?:\s+the)?\s+(?P<t>.+)$", re.I)

_SNAP_LEFT = re.compile(
    r"\bleft\s+half\b|\bsnap\s+(?:to\s+(?:the\s+)?)?left\b"
    r"|\bon\s+the\s+left\b|\bleft\s+side\s+of\s+(?:the\s+)?screen\b",
    re.I,
)
_SNAP_RIGHT = re.compile(
    r"\bright\s+half\b|\bsnap\s+(?:to\s+(?:the\s+)?)?right\b"
    r"|\bon\s+the\s+right\b|\bright\s+side\s+of\s+(?:the\s+)?screen\b",
    re.I,
)

_STRIP_TARGET = re.compile(
    r"\b(?:window|app|application|please|for me)\b",
    re.I,
)


def _clean_target(raw: str) -> str:
    t = (raw or "").strip()
    t = re.sub(r"^(?:the|my|a)\s+", "", t, flags=re.I)
    t = _STRIP_TARGET.sub(" ", t)
    t = _SNAP_LEFT.sub(" ", t)
    t = _SNAP_RIGHT.sub(" ", t)
    t = re.sub(
        r"\b(?:keep|put|place|move)\s+(?:it|that)?\s*(?:on|to)?\s*",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(r"\s+", " ", t).strip(" .,!?")
    return t


def classify(utterance: str) -> WindowIntent:
    text = (utterance or "").strip()
    if not text:
        return WindowIntent(WindowIntentKind.UNRELATED)
    # Media play+layout is owned by the local media path.
    if _MEDIA_PLAY.search(text):
        return WindowIntent(WindowIntentKind.UNRELATED)

    snap: SnapSide = None
    if _SNAP_LEFT.search(text):
        snap = "left"
    elif _SNAP_RIGHT.search(text):
        snap = "right"

    if snap and not (
        _FULLSCREEN.search(text)
        or _MAXIMIZE.search(text)
        or _MINIMIZE.search(text)
        or _FOCUS.search(text)
        or _CLOSE.match(text)
        or _RESTORE.match(text)
    ):
        # "snap vlc left" / "put vlc on the left half"
        t = text
        t = _SNAP_LEFT.sub(" ", t)
        t = _SNAP_RIGHT.sub(" ", t)
        t = re.sub(
            r"\b(?:keep|put|place|move|snap)\b",
            " ",
            t,
            flags=re.I,
        )
        return WindowIntent(WindowIntentKind.SNAP, target=_clean_target(t), snap=snap)

    if _FULLSCREEN.search(text):
        t = _FULLSCREEN.sub(" ", text)
        t = re.sub(r"\b(?:make|put|set|go)\b", " ", t, flags=re.I)
        return WindowIntent(WindowIntentKind.FULLSCREEN, target=_clean_target(t))

    if _MAXIMIZE.search(text):
        t = _MAXIMIZE.sub(" ", text)
        return WindowIntent(WindowIntentKind.MAXIMIZE, target=_clean_target(t))

    if _MINIMIZE_ALL.search(text):
        return WindowIntent(WindowIntentKind.MINIMIZE_ALL)

    if _MINIMIZE.search(text):
        t = _MINIMIZE.sub(" ", text)
        return WindowIntent(WindowIntentKind.MINIMIZE, target=_clean_target(t))

    m = _CLOSE.match(text)
    if m and not re.search(r"\b(?:tab|file|document)\b", text, re.I):
        return WindowIntent(WindowIntentKind.CLOSE, target=_clean_target(m.group("t")))

    m = _FOCUS.match(text)
    if m:
        return WindowIntent(WindowIntentKind.FOCUS, target=_clean_target(m.group("t")))

    m = _RESTORE.match(text)
    if m:
        return WindowIntent(WindowIntentKind.RESTORE, target=_clean_target(m.group("t")))

    return WindowIntent(WindowIntentKind.UNRELATED)
