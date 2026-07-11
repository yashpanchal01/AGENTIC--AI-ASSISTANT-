"""Classify Gmail / Calendar voice utterances (read vs write vs unrelated)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class GoogleIntentKind(Enum):
    UNRELATED = auto()
    # Read — Gmail
    GMAIL_UNREAD = auto()
    GMAIL_SEARCH = auto()
    GMAIL_THREAD = auto()
    # Read — Calendar
    CALENDAR_TODAY = auto()
    CALENDAR_NEXT = auto()
    CALENDAR_FREE_AT = auto()
    # Write / outward — always refuse
    WRITE_SEND = auto()
    WRITE_REPLY = auto()
    WRITE_FORWARD = auto()
    WRITE_CALENDAR = auto()


@dataclass(frozen=True)
class GoogleIntent:
    kind: GoogleIntentKind
    query: str = ""  # search terms, thread hint, or free-at time phrase


_WRITE_SEND = re.compile(
    r"\b(send|compose|draft)\b.*\b(email|mail|message)\b"
    r"|\b(email|mail|message)\b.*\b(to|send)\b",
    re.I,
)
_WRITE_REPLY = re.compile(r"\breply\b", re.I)
_WRITE_FORWARD = re.compile(r"\bforward\b", re.I)
_WRITE_CAL = re.compile(
    r"\b(create|add|schedule|book|make|set up|put)\b.*\b(event|meeting|appointment|calendar)\b"
    r"|\b(event|meeting|appointment)\b.*\b(create|add|schedule|book)\b"
    r"|\bcreate a calendar event\b",
    re.I,
)

_UNREAD = re.compile(
    r"\b(any|what'?s|whats|show|check|read)\b.*\b(new |unread )?(email|mail|inbox)\b"
    r"|\b(new|unread)\s+(email|mail|messages?)\b"
    r"|\bany new email\b",
    re.I,
)
_SEARCH = re.compile(
    r"\b(search|find|look\s*up|look for)\b.*\b(inbox|email|mail|gmail)\b"
    r"|\b(inbox|email|mail)\b.*\b(for|about)\b",
    re.I,
)
_THREAD = re.compile(
    r"\b(summarize|summary|read)\b.*\b(thread|conversation|email|mail)\b"
    r"|\bthread\b.*\b(about|on|regarding)\b",
    re.I,
)
_TODAY = re.compile(
    r"\b(what'?s|whats|what is)\b.*\b(on my )?(calendar|schedule)\b.*\btoday\b"
    r"|\btoday'?s?\b.*\b(calendar|schedule|agenda)\b"
    r"|\b(calendar|schedule)\b.*\btoday\b",
    re.I,
)
_NEXT = re.compile(
    r"\b(next|upcoming)\b.*\b(event|meeting|appointment)\b"
    r"|\bwhat'?s my next\b",
    re.I,
)
_FREE = re.compile(
    r"\b(am i|are we)\s+free\b"
    r"|\bfree\s+at\b"
    r"|\bis .+ free\b",
    re.I,
)


def classify(utterance: str) -> GoogleIntent:
    text = (utterance or "").strip()
    if not text:
        return GoogleIntent(GoogleIntentKind.UNRELATED)
    lower = text.lower()

    # Writes first — never mis-route a send as a search.
    # Forward before send: "forward the email to X" also matches the send "email…to" pattern.
    if _WRITE_FORWARD.search(text):
        return GoogleIntent(GoogleIntentKind.WRITE_FORWARD)
    if _WRITE_SEND.search(text):
        return GoogleIntent(GoogleIntentKind.WRITE_SEND)
    if _WRITE_REPLY.search(text) and any(
        k in lower for k in ("email", "mail", "message", "thread", "inbox")
    ):
        return GoogleIntent(GoogleIntentKind.WRITE_REPLY)
    if _WRITE_REPLY.search(text) and "saying" in lower:
        return GoogleIntent(GoogleIntentKind.WRITE_REPLY)
    if _WRITE_CAL.search(text):
        return GoogleIntent(GoogleIntentKind.WRITE_CALENDAR)

    if _UNREAD.search(text):
        return GoogleIntent(GoogleIntentKind.GMAIL_UNREAD)
    if _THREAD.search(text):
        hint = _extract_about(text)
        return GoogleIntent(GoogleIntentKind.GMAIL_THREAD, query=hint)
    if _SEARCH.search(text):
        q = _extract_search_query(text)
        return GoogleIntent(GoogleIntentKind.GMAIL_SEARCH, query=q)
    if _TODAY.search(text):
        return GoogleIntent(GoogleIntentKind.CALENDAR_TODAY)
    if _NEXT.search(text):
        return GoogleIntent(GoogleIntentKind.CALENDAR_NEXT)
    if _FREE.search(text):
        when = _extract_free_when(text)
        return GoogleIntent(GoogleIntentKind.CALENDAR_FREE_AT, query=when)

    return GoogleIntent(GoogleIntentKind.UNRELATED)


def _extract_search_query(text: str) -> str:
    m = re.search(
        r"\b(?:for|about|regarding)\s+(.+)$",
        text.strip(),
        re.I,
    )
    if m:
        return m.group(1).strip(" ?.!")
    return text


def _extract_about(text: str) -> str:
    m = re.search(r"\babout\s+(.+)$", text.strip(), re.I)
    if m:
        return m.group(1).strip(" ?.!")
    m = re.search(r"\bthread\s+(.+)$", text.strip(), re.I)
    if m:
        return m.group(1).strip(" ?.!")
    return text


def _extract_free_when(text: str) -> str:
    m = re.search(r"\bfree\s+at\s+(.+)$", text.strip(), re.I)
    if m:
        return m.group(1).strip(" ?.!")
    m = re.search(r"\bat\s+(\w+)$", text.strip(), re.I)
    if m:
        return m.group(1).strip(" ?.!")
    return text
