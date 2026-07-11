"""GoogleWorkspace: route voice intents to Gmail/Calendar readers (or refuse writes)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from jarvis.google.base import GoogleResult
from jarvis.google.intents import GoogleIntentKind, classify
from jarvis.types import Action


@runtime_checkable
class GmailReader(Protocol):
    def unread_summary(self) -> str: ...
    def search(self, query: str) -> str: ...
    def summarize_thread(self, hint: str) -> str: ...


@runtime_checkable
class CalendarReader(Protocol):
    def today_summary(self) -> str: ...
    def next_event(self) -> str: ...
    def free_at(self, when: str) -> str: ...


_READ_ONLY_REPLY = (
    "I won't {action} — Gmail and Calendar are read-only in v1. "
    "I can summarize mail or your schedule, but not send, reply, forward, or create events."
)


@dataclass
class GoogleWorkspaceImpl:
    """Concrete hub: intent classify → read APIs or explicit read-only refusal."""

    gmail: GmailReader | None = None
    calendar: CalendarReader | None = None
    signed_in: bool = True

    def try_handle(self, utterance: str) -> GoogleResult | None:
        intent = classify(utterance)
        if intent.kind is GoogleIntentKind.UNRELATED:
            return None

        if intent.kind in (
            GoogleIntentKind.WRITE_SEND,
            GoogleIntentKind.WRITE_REPLY,
            GoogleIntentKind.WRITE_FORWARD,
            GoogleIntentKind.WRITE_CALENDAR,
        ):
            action = {
                GoogleIntentKind.WRITE_SEND: "send email",
                GoogleIntentKind.WRITE_REPLY: "reply to email",
                GoogleIntentKind.WRITE_FORWARD: "forward email",
                GoogleIntentKind.WRITE_CALENDAR: "create calendar events",
            }[intent.kind]
            return GoogleResult(
                reply=_READ_ONLY_REPLY.format(action=action),
                actions=(),
                denied=True,
                ok=True,
            )

        if not self.signed_in:
            return GoogleResult(
                reply=(
                    "You're not signed in to Google yet. "
                    "Run jarvis --google-login once to connect Gmail and Calendar."
                ),
                actions=(),
                ok=False,
                error="not_signed_in",
            )

        try:
            return self._dispatch_read(intent.kind, intent.query)
        except Exception as exc:  # noqa: BLE001 — speak plain error
            return GoogleResult(
                reply="I couldn't reach Google right now.",
                actions=(),
                ok=False,
                error=type(exc).__name__,
            )

    def _dispatch_read(self, kind: GoogleIntentKind, query: str) -> GoogleResult:
        if kind is GoogleIntentKind.GMAIL_UNREAD:
            if self.gmail is None:
                raise RuntimeError("gmail_unavailable")
            return GoogleResult(
                reply=self.gmail.unread_summary(),
                actions=(Action(name="gmail_unread", detail=""),),
            )
        if kind is GoogleIntentKind.GMAIL_SEARCH:
            if self.gmail is None:
                raise RuntimeError("gmail_unavailable")
            return GoogleResult(
                reply=self.gmail.search(query),
                actions=(Action(name="gmail_search", detail=query),),
            )
        if kind is GoogleIntentKind.GMAIL_THREAD:
            if self.gmail is None:
                raise RuntimeError("gmail_unavailable")
            return GoogleResult(
                reply=self.gmail.summarize_thread(query),
                actions=(Action(name="gmail_thread", detail=query),),
            )
        if kind is GoogleIntentKind.CALENDAR_TODAY:
            if self.calendar is None:
                raise RuntimeError("calendar_unavailable")
            return GoogleResult(
                reply=self.calendar.today_summary(),
                actions=(Action(name="calendar_today", detail=""),),
            )
        if kind is GoogleIntentKind.CALENDAR_NEXT:
            if self.calendar is None:
                raise RuntimeError("calendar_unavailable")
            return GoogleResult(
                reply=self.calendar.next_event(),
                actions=(Action(name="calendar_next", detail=""),),
            )
        if kind is GoogleIntentKind.CALENDAR_FREE_AT:
            if self.calendar is None:
                raise RuntimeError("calendar_unavailable")
            return GoogleResult(
                reply=self.calendar.free_at(query),
                actions=(Action(name="calendar_free_at", detail=query),),
            )
        return GoogleResult(reply="I'm not sure how to help with that Google request.")


def build_google_workspace(*, force_fake: bool = False) -> GoogleWorkspaceImpl:
    """Build workspace from stored OAuth tokens, or unsigned / fake for demos."""
    if force_fake:
        from jarvis.google.fake import sample_workspace

        return sample_workspace(signed_in=True)

    from jarvis.google.oauth import is_signed_in, load_credentials

    if not is_signed_in():
        return GoogleWorkspaceImpl(signed_in=False)

    try:
        from jarvis.google.calendar_api import LiveCalendar
        from jarvis.google.gmail_api import LiveGmail

        creds = load_credentials()
        if creds is None:
            return GoogleWorkspaceImpl(signed_in=False)
        return GoogleWorkspaceImpl(
            gmail=LiveGmail(creds),
            calendar=LiveCalendar(creds),
            signed_in=True,
        )
    except Exception:  # noqa: BLE001 — degrade rather than crash CLI
        return GoogleWorkspaceImpl(signed_in=False)
