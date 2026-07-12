"""Classify smart app-open utterances."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class AppIntentKind(Enum):
    UNRELATED = auto()
    # Focus if running, else launch. Never force a second instance unless NEW.
    OPEN = auto()
    # Explicit new instance even if already running.
    OPEN_NEW = auto()
    # Focus only — do not launch if missing.
    FOCUS = auto()


@dataclass(frozen=True)
class AppIntent:
    kind: AppIntentKind
    app: str = ""  # spoken target after chrome stripped


# Don't steal media / spotify / window layout phrases.
_NOT_APP = re.compile(
    r"\b(?:downloads?|desktop|documents?|videos?|movie|film|mp4|mkv|mp3)\b"
    r"|\bplaylist\b|\blo-?fi\b|\bvolume\b|\bskip\b"
    r"|\bfull[\s-]?screen\b|\bleft\s+half\b|\bright\s+half\b"
    r"|\bfrom\s+(?:my\s+)?downloads?\b",
    re.I,
)

# True when the user wants a *new* instance, not focus-existing.
_WANTS_NEW = re.compile(
    r"\bnew\b"
    r"|\banother\b"
    r"|\bforce\s+new\b",
    re.I,
)

_OPEN = re.compile(
    r"^\s*(?:please\s+)?(?:jarvis[,\s]+)?"
    r"(?:open|launch|start|run)\s+(?:up\s+)?(?P<app>.+?)\s*$",
    re.I,
)

_FOCUS = re.compile(
    r"^\s*(?:please\s+)?(?:jarvis[,\s]+)?"
    r"(?:focus|switch\s+to|bring\s+up|activate|go\s+to)\s+(?:the\s+)?(?P<app>.+?)\s*$",
    re.I,
)


def classify(utterance: str) -> AppIntent:
    text = (utterance or "").strip()
    if not text:
        return AppIntent(AppIntentKind.UNRELATED)
    if _NOT_APP.search(text):
        return AppIntent(AppIntentKind.UNRELATED)

    m = _OPEN.match(text)
    if m:
        raw = m.group("app")
        app = _clean_app(raw)
        if not app:
            return AppIntent(AppIntentKind.UNRELATED)
        # "open new brave" / "open a new brave window" / "open another chrome"
        if _WANTS_NEW.search(raw) or _WANTS_NEW.search(text):
            # Avoid treating plain "open windows notepad" style false positives —
            # only force-new when "new/another" appears in the app chunk or
            # right after open.
            if _WANTS_NEW.search(raw) or re.search(
                r"\b(?:open|launch|start|run)\s+(?:up\s+)?(?:a\s+)?(?:new|another)\b",
                text,
                re.I,
            ):
                return AppIntent(AppIntentKind.OPEN_NEW, app=app)
        return AppIntent(AppIntentKind.OPEN, app=app)

    m = _FOCUS.match(text)
    if m:
        app = _clean_app(m.group("app"))
        if not app:
            return AppIntent(AppIntentKind.UNRELATED)
        return AppIntent(AppIntentKind.FOCUS, app=app)

    return AppIntent(AppIntentKind.UNRELATED)


def _clean_app(raw: str) -> str:
    t = (raw or "").strip()
    t = re.sub(r"^(?:the|my|a)\s+", "", t, flags=re.I)
    t = re.sub(r"\ba\s+new\b", " ", t, flags=re.I)
    t = re.sub(r"\bnew\b", " ", t, flags=re.I)
    t = re.sub(
        r"\b(?:app|application|please|for me|window|instance|tab)\b",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(r"\s+", " ", t).strip(" .,!?")
    return t
