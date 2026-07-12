"""Classify everyday Spotify voice utterances (issue 09, user stories 26–28).

Covered: play/pause/resume/skip, play by song/artist/playlist name,
now-playing, and volume. "Open Spotify" (app launch) stays with the brain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class SpotifyIntentKind(Enum):
    UNRELATED = auto()
    PLAY_NAMED = auto()  # query + hint: "track" | "artist" | "playlist" | "any"
    RESUME = auto()
    PAUSE = auto()
    NEXT = auto()
    NOW_PLAYING = auto()
    VOLUME_SET = auto()  # level 0–100
    VOLUME_UP = auto()
    VOLUME_DOWN = auto()


@dataclass(frozen=True)
class SpotifyIntent:
    kind: SpotifyIntentKind
    query: str = ""
    hint: str = "any"  # for PLAY_NAMED
    level: int | None = None  # for VOLUME_SET


# App launch ("open spotify") is the brain's job (PRD story 14) — never ours.
_APP_LAUNCH = re.compile(r"\b(open|launch|start)\s+(up\s+)?spotify\b", re.I)

_NOW_PLAYING = re.compile(
    r"\bwhat(?:'s| is)?\s+(?:currently\s+|now\s+)?playing\b"
    r"|\bnow playing\b"
    r"|\bwhat(?:'s| is)?\s+(?:this|that)\s+(?:song|track)\b"
    r"|\bwhat\s+(?:song|track)\s+is\s+(?:this|that|playing)\b"
    r"|\bwhich\s+(?:song|track)\s+is\s+this\b",
    re.I,
)

# Bare skip/next commands ("skip", "next song") or explicit music context.
_NEXT_BARE = re.compile(
    r"^\s*(?:skip|next)(?:\s+(?:it|this|that|one|song|track|please))*\s*$", re.I
)
_NEXT_MUSIC = re.compile(
    r"\b(?:skip|next)\b.*\b(?:song|track|music|tune)\b"
    r"|\bplay the next\b",
    re.I,
)

_PAUSE_BARE = re.compile(r"^\s*pause(?:\s+(?:it|that|please))*\s*$", re.I)
_PAUSE_MUSIC = re.compile(
    r"\bpause\b.*\b(?:music|song|track|spotify|playback)\b"
    r"|\b(?:music|song|spotify)\b.*\bpause\b"
    r"|\b(?:stop|hold)\b.*\b(?:music|song|track|spotify|playback)\b",
    re.I,
)

_RESUME_BARE = re.compile(
    r"^\s*(?:resume|unpause|play)(?:\s+(?:it|that|please))*\s*$", re.I
)
_RESUME_MUSIC = re.compile(
    r"\bresume\b.*\b(?:music|song|track|spotify|playback|playing)\b"
    r"|\bunpause\b"
    r"|\bkeep\s+playing\b"
    r"|\bcontinue\b.*\b(?:music|song|playing|playback)\b",
    re.I,
)

_VOLUME_NUMBER = re.compile(
    r"\bvolume\b[^0-9%]*?(\d{1,3})\s*(?:percent|%)?\b", re.I
)
_VOLUME_WORDS: dict[str, int] = {
    "ten": 10,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
}
_VOLUME_WORD = re.compile(
    r"\bvolume\b.*?\b(" + "|".join(_VOLUME_WORDS) + r")\b(\s*percent)?", re.I
)
_VOLUME_UP = re.compile(
    r"\bvolume\s+up\b"
    r"|\bturn\s+(?:it|the\s+volume|the\s+music)\s+up\b"
    r"|\blouder\b"
    r"|\b(?:raise|increase)\b.*\bvolume\b"
    r"|\bcrank\s+it\s+up\b",
    re.I,
)
_VOLUME_DOWN = re.compile(
    r"\bvolume\s+down\b"
    r"|\bturn\s+(?:it|the\s+volume|the\s+music)\s+down\b"
    r"|\b(?:quieter|softer)\b"
    r"|\b(?:lower|decrease|reduce)\b.*\bvolume\b",
    re.I,
)

_PLAY = re.compile(
    r"^\s*(?:please\s+)?(?:jarvis[,\s]+)?(?:can you\s+|could you\s+)?"
    r"(?:play|put on)\s+(?P<rest>.+?)\s*$",
    re.I,
)
# "play some music" and friends mean "resume", not a named search.
_GENERIC_PLAY = frozenset(
    {
        "music",
        "some music",
        "the music",
        "something",
        "anything",
        "a song",
        "some songs",
        "a track",
    }
)


def classify(utterance: str) -> SpotifyIntent:
    text = (utterance or "").strip()
    if not text:
        return SpotifyIntent(SpotifyIntentKind.UNRELATED)
    if _APP_LAUNCH.search(text):
        return SpotifyIntent(SpotifyIntentKind.UNRELATED)

    if _NOW_PLAYING.search(text):
        return SpotifyIntent(SpotifyIntentKind.NOW_PLAYING)

    if _NEXT_BARE.match(text) or _NEXT_MUSIC.search(text):
        return SpotifyIntent(SpotifyIntentKind.NEXT)

    if _PAUSE_BARE.match(text) or _PAUSE_MUSIC.search(text):
        return SpotifyIntent(SpotifyIntentKind.PAUSE)

    if _RESUME_BARE.match(text) or _RESUME_MUSIC.search(text):
        return SpotifyIntent(SpotifyIntentKind.RESUME)

    level = _extract_volume_level(text)
    if level is not None:
        return SpotifyIntent(SpotifyIntentKind.VOLUME_SET, level=_clamp(level))
    if _VOLUME_UP.search(text):
        return SpotifyIntent(SpotifyIntentKind.VOLUME_UP)
    if _VOLUME_DOWN.search(text):
        return SpotifyIntent(SpotifyIntentKind.VOLUME_DOWN)

    m = _PLAY.match(text)
    if m:
        return _parse_play(m.group("rest"))

    return SpotifyIntent(SpotifyIntentKind.UNRELATED)


def _extract_volume_level(text: str) -> int | None:
    m = _VOLUME_NUMBER.search(text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    m = _VOLUME_WORD.search(text)
    if m:
        return _VOLUME_WORDS[m.group(1).lower()]
    return None


def _clamp(level: int) -> int:
    return max(0, min(100, level))


def _parse_play(rest: str) -> SpotifyIntent:
    """Split "play …" into a search query + type hint (song/artist/playlist)."""
    q = rest.strip(" ?.!,")
    # "play me some jazz" → "some jazz"
    q = re.sub(r"^me\s+", "", q, flags=re.I)
    # "… on spotify" suffix carries no search value.
    q = re.sub(r"\s+on\s+spotify$", "", q, flags=re.I).strip()

    if not q or q.lower() in _GENERIC_PLAY:
        return SpotifyIntent(SpotifyIntentKind.RESUME)

    # Playlist: "the playlist chill vibes" / "my chill vibes playlist"
    m = re.match(r"^(?:the\s+|my\s+)?playlist\s+(?:called\s+|named\s+)?(.+)$", q, re.I)
    if m:
        return SpotifyIntent(
            SpotifyIntentKind.PLAY_NAMED, query=m.group(1).strip(), hint="playlist"
        )
    m = re.match(r"^(?:my\s+|the\s+)?(.+?)\s+playlist$", q, re.I)
    if m:
        return SpotifyIntent(
            SpotifyIntentKind.PLAY_NAMED, query=m.group(1).strip(), hint="playlist"
        )

    # Artist: "the artist daft punk" / "something by daft punk" / "songs by queen"
    m = re.match(r"^(?:the\s+)?(?:artist|band)\s+(.+)$", q, re.I)
    if m:
        return SpotifyIntent(
            SpotifyIntentKind.PLAY_NAMED, query=m.group(1).strip(), hint="artist"
        )
    m = re.match(
        r"^(?:something|anything|songs?|tracks?|music|stuff)\s+by\s+(.+)$", q, re.I
    )
    if m:
        return SpotifyIntent(
            SpotifyIntentKind.PLAY_NAMED, query=m.group(1).strip(), hint="artist"
        )

    # Track: "the song bohemian rhapsody" / "bohemian rhapsody by queen"
    m = re.match(r"^(?:the\s+)?(?:song|track)\s+(.+)$", q, re.I)
    if m:
        return SpotifyIntent(
            SpotifyIntentKind.PLAY_NAMED, query=m.group(1).strip(), hint="track"
        )
    if re.search(r"\s+by\s+", q, re.I):
        return SpotifyIntent(SpotifyIntentKind.PLAY_NAMED, query=q, hint="track")

    # "some lo-fi" → generic search for lo-fi.
    q = re.sub(r"^some\s+", "", q, flags=re.I).strip()
    return SpotifyIntent(SpotifyIntentKind.PLAY_NAMED, query=q, hint="any")
