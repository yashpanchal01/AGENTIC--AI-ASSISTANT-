"""In-process fake Gmail/Calendar for automated tests — no network."""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.google.workspace import GoogleWorkspaceImpl


@dataclass
class FakeGmail:
    """Scriptable Gmail reader with sample inbox data."""

    unread_text: str = (
        "You have 2 unread emails. "
        "The latest is an invoice from Acme for March, "
        "and a note from Sam about lunch."
    )
    search_hits: dict[str, str] = field(
        default_factory=lambda: {
            "invoice": "Found 1 email: invoice from Acme for March, subject 'Invoice #442'.",
            "invoices": "Found 1 email: invoice from Acme for March, subject 'Invoice #442'.",
        }
    )
    threads: dict[str, str] = field(
        default_factory=lambda: {
            "project kickoff": (
                "Thread about the project kickoff: Sam proposed Tuesday 10am, "
                "you agreed, and the agenda is goals and owners."
            ),
            "kickoff": (
                "Thread about the project kickoff: Sam proposed Tuesday 10am, "
                "you agreed, and the agenda is goals and owners."
            ),
        }
    )

    def unread_summary(self) -> str:
        return self.unread_text

    def search(self, query: str) -> str:
        q = (query or "").lower()
        for key, summary in self.search_hits.items():
            if key in q or q in key:
                return summary
        if "invoice" in q:
            return self.search_hits.get(
                "invoice",
                f"No emails matched {query!r}.",
            )
        return f"No emails matched {query!r}."

    def summarize_thread(self, hint: str) -> str:
        h = (hint or "").lower()
        for key, summary in self.threads.items():
            if key in h or h in key:
                return summary
        if "kickoff" in h or "project" in h:
            return self.threads["project kickoff"]
        return f"I couldn't find a thread about {hint}."


@dataclass
class FakeCalendar:
    """Scriptable Calendar reader with sample schedule data."""

    today_text: str = "Today you have Standup at 9 AM and Design review at 2 PM."
    next_text: str = "Your next event is Standup at 9 AM."
    free_replies: dict[str, str] = field(
        default_factory=lambda: {
            "three": "Yes, you're free at three.",
            "3": "Yes, you're free at three.",
            "3pm": "Yes, you're free at three.",
            "two": "No, you're busy at two — Design review.",
            "2": "No, you're busy at two — Design review.",
            "2pm": "No, you're busy at two — Design review.",
        }
    )
    default_free: str = "Yes, you're free at that time."

    def today_summary(self) -> str:
        return self.today_text

    def next_event(self) -> str:
        return self.next_text

    def free_at(self, when: str) -> str:
        key = (when or "").lower().strip()
        for k, v in self.free_replies.items():
            if k in key or key in k:
                return v
        return self.default_free


class FakeGoogleWorkspace(GoogleWorkspaceImpl):
    """Alias for tests that want an explicit Fake* name."""

    def __init__(
        self,
        *,
        gmail: FakeGmail | None = None,
        calendar: FakeCalendar | None = None,
        signed_in: bool = True,
    ) -> None:
        super().__init__(
            gmail=gmail or FakeGmail(),
            calendar=calendar or FakeCalendar(),
            signed_in=signed_in,
            works_offline=True,
        )


def sample_workspace(
    *,
    signed_in: bool = True,
    gmail: FakeGmail | None = None,
    calendar: FakeCalendar | None = None,
) -> GoogleWorkspaceImpl:
    """Ready-to-use workspace with sample mail and calendar data."""
    return GoogleWorkspaceImpl(
        gmail=gmail or FakeGmail(),
        calendar=calendar or FakeCalendar(),
        signed_in=signed_in,
        works_offline=True,
    )
