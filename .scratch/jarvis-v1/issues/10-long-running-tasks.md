# 10 — Long tasks: background, announce done/fail, cancel

Status: done

## What to build

When work will take longer than ~20s, JARVIS acknowledges ("on it"), continues in the background, keeps overlay in a working state, and announces completion or failure aloud. "Jarvis, cancel" aborts the in-flight long task. User is never held at the counter for multi-step work.

## Acceptance criteria

- [x] Long work is backgrounded with a spoken acknowledgment
- [x] Overlay reflects ongoing work while the user does other things
- [x] Completion and failure both get a spoken announcement
- [x] Wake-word cancel aborts the running long task
- [x] Short commands remain on the normal foreground path

## Blocked by

- 02 — Headless core loop
- 05 — Aurora overlay

## User stories covered

44–45

## Comments

Implemented via timeout-race in `jarvis/tasks.py` (`LongTaskService`):
brain.ask runs on a worker; if still running past `long_task_threshold_s`
(default 20s, `JARVIS_LONG_TASK_S`), speaks "On it.", returns
`CommandResult.backgrounded=True`, keeps overlay WORKING, announces
completion/failure when done. Cancel utterances + `brain.cancel()` abort
in-flight work. Wired through core/voice/overlay/pipeline/session/CLI.
Tests: `tests/test_long_tasks.py`.
