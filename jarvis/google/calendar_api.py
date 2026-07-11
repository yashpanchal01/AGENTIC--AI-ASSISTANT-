"""Live Google Calendar API reader (readonly scope only)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


class LiveCalendar:
    """Calendar REST via google-api-python-client — read-only methods only."""

    def __init__(self, credentials: Any, *, tz_name: str | None = None) -> None:
        self._creds = credentials
        self._service = None
        self._tz_name = tz_name

    def _svc(self):
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build(
                "calendar", "v3", credentials=self._creds, cache_discovery=False
            )
        return self._service

    def _local_tz(self):
        if self._tz_name:
            try:
                return ZoneInfo(self._tz_name)
            except Exception:  # noqa: BLE001
                pass
        return datetime.now().astimezone().tzinfo or timezone.utc

    def today_summary(self) -> str:
        tz = self._local_tz()
        now = datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        events = self._list_events(start, end, max_results=10)
        if not events:
            return "Your calendar is clear today."
        parts = [self._fmt_event(e, tz) for e in events]
        if len(parts) == 1:
            return f"Today you have {parts[0]}."
        return "Today you have " + "; ".join(parts) + "."

    def next_event(self) -> str:
        tz = self._local_tz()
        now = datetime.now(tz)
        end = now + timedelta(days=14)
        events = self._list_events(now, end, max_results=1)
        if not events:
            return "You have no upcoming events on your calendar."
        return f"Your next event is {self._fmt_event(events[0], tz)}."

    def free_at(self, when: str) -> str:
        tz = self._local_tz()
        target = parse_spoken_time(when, now=datetime.now(tz))
        if target is None:
            return f"I wasn't sure what time you meant by {when!r}."
        window_end = target + timedelta(minutes=30)
        events = self._list_events(target, window_end, max_results=5)
        spoken = format_spoken_clock(target)
        if not events:
            return f"Yes, you're free at {spoken}."
        title = events[0].get("summary") or "an event"
        return f"No, you're busy at {spoken} — {title}."

    def _list_events(
        self,
        start: datetime,
        end: datetime,
        *,
        max_results: int,
    ) -> list[dict[str, Any]]:
        svc = self._svc()
        resp = (
            svc.events()
            .list(
                calendarId="primary",
                timeMin=_rfc3339(start),
                timeMax=_rfc3339(end),
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
            )
            .execute()
        )
        return list(resp.get("items") or [])

    def _fmt_event(self, event: dict[str, Any], tz) -> str:
        title = event.get("summary") or "(no title)"
        start = event.get("start") or {}
        if "dateTime" in start:
            dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            else:
                dt = dt.astimezone(tz)
            return f"{title} at {format_spoken_clock(dt)}"
        return f"{title} (all day)"


def _rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


_WORD_HOURS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "noon": 12,
    "midnight": 0,
}


def parse_spoken_time(when: str, *, now: datetime) -> datetime | None:
    """Best-effort parse of phrases like 'three', '3pm', '15:00'."""
    text = (when or "").strip().lower()
    if not text:
        return None

    if "noon" in text:
        return now.replace(hour=12, minute=0, second=0, microsecond=0)
    if "midnight" in text:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = (m.group(3) or "").replace(".", "")
        if ampm.startswith("p") and hour < 12:
            hour += 12
        elif ampm.startswith("a") and hour == 12:
            hour = 0
        elif not ampm and 1 <= hour <= 7:
            hour += 12
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    for word, hour in _WORD_HOURS.items():
        if re.search(rf"\b{word}\b", text):
            h = hour
            if "p.m" in text or "pm" in text:
                if h < 12:
                    h += 12
            elif "a.m" in text or "am" in text:
                if h == 12:
                    h = 0
            elif word not in ("noon", "midnight") and 1 <= h <= 7:
                h += 12
            return now.replace(hour=h, minute=0, second=0, microsecond=0)

    return None


def format_spoken_clock(dt: datetime) -> str:
    hour = dt.hour
    minute = dt.minute
    suffix = "AM" if hour < 12 else "PM"
    h12 = hour % 12
    if h12 == 0:
        h12 = 12
    if minute == 0:
        return f"{h12} {suffix}"
    return f"{h12}:{minute:02d} {suffix}"
