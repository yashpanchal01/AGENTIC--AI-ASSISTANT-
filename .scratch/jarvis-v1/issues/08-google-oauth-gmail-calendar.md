# 08 — Google OAuth: Gmail + Calendar read-only

Status: done

## What to build

One-time Google OAuth covering Gmail and Calendar. JARVIS can summarize unread mail, search/summarize threads, and answer schedule questions (today, next event, free/busy). Access is strictly read-only — send/reply/forward/create events are refused even if asked. Tokens stored securely and never in markdown memory notes.

## Acceptance criteria

- [x] One OAuth sign-in covers Gmail and Calendar
- [x] "Any new email?" / search / thread summary work as spoken answers
- [x] Today / next event / free-time style calendar questions work
- [x] Any send/reply/forward or calendar-write request is declined with a clear reason
- [x] Tokens are not stored in human-readable memory notes

## Blocked by

- 02 — Headless core loop

## User stories covered

20–25

## Comments
