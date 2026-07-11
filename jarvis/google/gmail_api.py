"""Live Gmail API reader (readonly scope only)."""

from __future__ import annotations

from email.utils import parseaddr
from typing import Any


class LiveGmail:
    """Gmail REST via google-api-python-client — read-only methods only."""

    def __init__(self, credentials: Any) -> None:
        self._creds = credentials
        self._service = None

    def _svc(self):
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build(
                "gmail", "v1", credentials=self._creds, cache_discovery=False
            )
        return self._service

    def unread_summary(self, *, limit: int = 5) -> str:
        svc = self._svc()
        resp = (
            svc.users()
            .messages()
            .list(userId="me", q="is:unread", maxResults=limit)
            .execute()
        )
        messages = resp.get("messages") or []
        if not messages:
            return "You have no unread email."

        snippets: list[str] = []
        for m in messages[:limit]:
            meta = (
                svc.users()
                .messages()
                .get(
                    userId="me",
                    id=m["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject"],
                )
                .execute()
            )
            headers = {
                h["name"].lower(): h["value"]
                for h in (meta.get("payload") or {}).get("headers") or []
            }
            who = parseaddr(headers.get("from", ""))[0] or headers.get("from", "someone")
            subject = headers.get("subject") or "(no subject)"
            snippets.append(f"{subject} from {who}")

        n = len(messages)
        listed = "; ".join(snippets)
        if n == 1:
            return f"You have 1 unread email: {snippets[0]}."
        more = "" if n <= limit else f" Showing the latest {limit}."
        return f"You have {n} unread emails: {listed}.{more}"

    def search(self, query: str, *, limit: int = 5) -> str:
        q = (query or "").strip()
        if not q:
            return "What should I search for in your inbox?"
        svc = self._svc()
        resp = (
            svc.users()
            .messages()
            .list(userId="me", q=q, maxResults=limit)
            .execute()
        )
        messages = resp.get("messages") or []
        if not messages:
            return f"I didn't find any emails matching {q}."

        lines: list[str] = []
        for m in messages[:limit]:
            meta = (
                svc.users()
                .messages()
                .get(
                    userId="me",
                    id=m["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject"],
                )
                .execute()
            )
            headers = {
                h["name"].lower(): h["value"]
                for h in (meta.get("payload") or {}).get("headers") or []
            }
            subject = headers.get("subject") or "(no subject)"
            lines.append(subject)

        joined = "; ".join(lines)
        return f"I found {len(messages)} email(s) for {q}: {joined}."

    def summarize_thread(self, hint: str) -> str:
        q = (hint or "").strip()
        if not q:
            return "Which thread should I summarize?"
        svc = self._svc()
        resp = (
            svc.users()
            .messages()
            .list(userId="me", q=q, maxResults=1)
            .execute()
        )
        messages = resp.get("messages") or []
        if not messages:
            return f"I couldn't find a thread about {q}."

        msg = (
            svc.users()
            .messages()
            .get(userId="me", id=messages[0]["id"], format="full")
            .execute()
        )
        thread_id = msg.get("threadId")
        thread = (
            svc.users()
            .threads()
            .get(userId="me", id=thread_id, format="metadata")
            .execute()
        )
        thread_msgs = thread.get("messages") or []
        subjects: list[str] = []
        senders: list[str] = []
        for tm in thread_msgs[:8]:
            headers = {
                h["name"].lower(): h["value"]
                for h in (tm.get("payload") or {}).get("headers") or []
            }
            if "subject" in headers and headers["subject"] not in subjects:
                subjects.append(headers["subject"])
            who = parseaddr(headers.get("from", ""))[0] or headers.get("from", "")
            if who and who not in senders:
                senders.append(who)
        subject = subjects[0] if subjects else q
        people = ", ".join(senders[:5]) if senders else "unknown senders"
        n = len(thread_msgs)
        snippet = (msg.get("snippet") or "").strip()
        body = f"Thread “{subject}” has {n} message(s) between {people}."
        if snippet:
            body += f" Latest: {snippet}"
        return body
