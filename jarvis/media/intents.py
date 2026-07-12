"""Classify utterances that mean “play/open a local file”, not Spotify.

Rules of thumb:
- Bare **open/launch/start X** → app launch → leave to the brain (not media).
- **play/watch** + local cues, or find+play, or file extension → local media.
- Ambiguous **play X** may soft-match a file; never steal browser/app names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Literal

SnapSide = Literal["left", "right"] | None


class MediaIntentKind(Enum):
    UNRELATED = auto()
    PLAY_LOCAL = auto()
    PLAY_IF_MATCH = auto()


@dataclass(frozen=True)
class MediaIntent:
    kind: MediaIntentKind
    query: str = ""
    fullscreen: bool = False
    snap: SnapSide = None


# Everyday apps — never treat as a media title (PLAY_IF_MATCH).
_APP_NAMES = frozenset(
    {
        "brave",
        "chrome",
        "edge",
        "firefox",
        "opera",
        "notepad",
        "calculator",
        "calc",
        "spotify",
        "discord",
        "slack",
        "teams",
        "code",
        "vscode",
        "terminal",
        "powershell",
        "cmd",
        "explorer",
        "settings",
        "word",
        "excel",
        "outlook",
        "steam",
        "vlc",
        "paint",
        "photos",
        "store",
        "zoom",
        "whatsapp",
        "telegram",
        "obsidian",
        "cursor",
        "grok",
    }
)

_MUSIC_CLEAR = re.compile(
    r"\bspotify\b"
    r"|\bplaylist\b"
    r"|\balbum\b"
    r"|\blo-?fi\b"
    r"|\b(?:song|track|tune|music)\b"
    r"|\b(?:skip|next|pause|resume|unpause)\b"
    r"|\bvolume\b"
    r"|\bwhat(?:'s| is)?\s+(?:playing|this song)\b"
    r"|\b(?:something|songs?|tracks?|music|stuff)\s+by\b"
    r"|\bby\s+[a-z0-9]",
    re.I,
)

_LOCAL_CUE = re.compile(
    r"\bdownloads?\b"
    r"|\bdesktop\b"
    r"|\bdocuments?\b"
    r"|\bvideos?\b"
    r"|\bmovie\b"
    r"|\bfilm\b"
    r"|\b(?:mp4|mkv|avi|mov|webm|m4v|mp3|flac|wav)\b"
    r"|\bfind\b.+\b(?:play|open|watch)\b"
    r"|\b(?:play|open|watch)\b.+\bfind\b"
    r"|\bgo to\b.+\b(?:play|open)\b",
    re.I,
)

# Media verbs that can mean "play a file". "open/launch/start" alone = apps.
_MEDIA_VERB = re.compile(
    r"\b(?:play|watch)\b"
    r"|\bfind\b.+\b(?:play|open|watch)\b"
    r"|\bopen\b.+\b(?:movie|film|video|file|mp4|mkv|mp3)\b"
    r"|\bopen\b.+\b(?:from|in)\s+(?:my\s+)?(?:downloads?|desktop|documents?|videos?)\b",
    re.I,
)

# Bare app launch — always leave for the brain.
_BARE_APP_OPEN = re.compile(
    r"^\s*(?:please\s+)?(?:jarvis[,\s]+)?"
    r"(?:open|launch|start|run)\s+(?:up\s+)?(?P<app>[\w][\w .'-]{0,40}?)\s*$",
    re.I,
)

_FULLSCREEN = re.compile(
    r"\bin\s+full[\s-]?screen\b"
    r"|\bfull[\s-]?screen(?:ed|ing)?\b"
    r"|\bfullscreen(?:ed|ing)?\b",
    re.I,
)

_SNAP_LEFT = re.compile(
    r"\bleft\s+half\b"
    r"|\bhalf\s+(?:of\s+)?(?:the\s+)?(?:screen\s+)?left\b"
    r"|\bsnap\s+(?:to\s+(?:the\s+)?)?left\b"
    r"|\b(?:keep|put|place|move)\b.+\bleft\s+half\b"
    r"|\bon\s+the\s+left\b"
    r"|\bleft\s+side\s+of\s+(?:the\s+)?screen\b",
    re.I,
)
_SNAP_RIGHT = re.compile(
    r"\bright\s+half\b"
    r"|\bhalf\s+(?:of\s+)?(?:the\s+)?(?:screen\s+)?right\b"
    r"|\bsnap\s+(?:to\s+(?:the\s+)?)?right\b"
    r"|\b(?:keep|put|place|move)\b.+\bright\s+half\b"
    r"|\bon\s+the\s+right\b"
    r"|\bright\s+side\s+of\s+(?:the\s+)?screen\b",
    re.I,
)

_PLACEMENT_STRIP = re.compile(
    r"\b(?:keep|put|place|move)\s+(?:it|that|this|the\s+window)?\s*"
    r"(?:on|to|at)?\s*(?:the\s+)?(?:left|right)\s+"
    r"(?:half|side)(?:\s+of\s+(?:the\s+)?screen)?\b"
    r"|\b(?:on|to)\s+the\s+(?:left|right)(?:\s+half|\s+side)?(?:\s+of\s+(?:the\s+)?screen)?\b"
    r"|\b(?:left|right)\s+half(?:\s+of\s+(?:the\s+)?screen)?\b"
    r"|\bsnap\s+(?:to\s+(?:the\s+)?)?(?:left|right)\b"
    r"|\b(?:left|right)\s+side\s+of\s+(?:the\s+)?screen\b",
    re.I,
)


def wants_fullscreen(text: str) -> bool:
    return bool(_FULLSCREEN.search(text or ""))


def parse_snap(text: str) -> SnapSide:
    t = text or ""
    if _SNAP_LEFT.search(t):
        return "left"
    if _SNAP_RIGHT.search(t):
        return "right"
    return None


def classify(utterance: str) -> MediaIntent:
    text = (utterance or "").strip()
    if not text:
        return MediaIntent(MediaIntentKind.UNRELATED)

    # "open brave" / "launch chrome" / "start notepad" → brain, not media.
    m_app = _BARE_APP_OPEN.match(text)
    if m_app:
        return MediaIntent(MediaIntentKind.UNRELATED)

    if _MUSIC_CLEAR.search(text):
        return MediaIntent(MediaIntentKind.UNRELATED)

    # Need a real media verb (play/watch/find…play), not bare open-app.
    if not _MEDIA_VERB.search(text) and not (
        _LOCAL_CUE.search(text) and re.search(r"\b(?:open|play|watch)\b", text, re.I)
    ):
        return MediaIntent(MediaIntentKind.UNRELATED)

    fs = wants_fullscreen(text)
    snap = parse_snap(text)
    query = extract_query(text)
    if not query or len(query) < 2:
        return MediaIntent(MediaIntentKind.UNRELATED)

    # Known app name alone (e.g. leftover) — never soft-match media.
    if query.lower().strip() in _APP_NAMES:
        return MediaIntent(MediaIntentKind.UNRELATED)

    if _LOCAL_CUE.search(text) or fs or snap:
        return MediaIntent(
            MediaIntentKind.PLAY_LOCAL, query=query, fullscreen=fs, snap=snap
        )
    # Ambiguous "play X" only — never "open X"
    if re.search(r"\b(?:play|watch)\b", text, re.I):
        return MediaIntent(
            MediaIntentKind.PLAY_IF_MATCH, query=query, fullscreen=fs, snap=snap
        )
    return MediaIntent(MediaIntentKind.UNRELATED)


def extract_query(text: str) -> str:
    """Strip command chrome; leave the title/name to search for."""
    t = (text or "").strip()
    t = re.sub(r"^(?:please\s+)?(?:jarvis[,\s]+)?", "", t, flags=re.I)
    t = _FULLSCREEN.sub(" ", t)
    t = _PLACEMENT_STRIP.sub(" ", t)
    t = _SNAP_LEFT.sub(" ", t)
    t = _SNAP_RIGHT.sub(" ", t)
    t = re.sub(
        r"\b(?:go\s+to|open|in|from)\s+(?:my\s+|the\s+)?"
        r"(?:downloads?|desktop|documents?|videos?)(?:\s+folder)?\b",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(
        r"\b(?:my\s+|the\s+)?(?:downloads?|desktop|documents?|videos?)(?:\s+folder)?\b",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(r"\b(?:find|search for|look for|locate)\b", " ", t, flags=re.I)
    t = re.sub(
        r"\b(?:and\s+)?(?:play|open|watch|launch)\s+(?:it|that|this)?\b",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(r"\b(?:play|open|watch|launch|go to|folder)\b", " ", t, flags=re.I)
    t = re.sub(
        r"\b(?:movie|film|video|clip|file|media)\b",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(
        r"\b(?:with the default(?: media)? player|using start|"
        r"default media player|reply in one short sentence when done)\b",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(r"\.(?:mp4|mkv|avi|mov|wmv|webm|m4v|mp3|flac|wav|m4a)\b", " ", t, flags=re.I)
    t = re.sub(r"[^\w\s'\-()]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .,'!?-")
    return t
