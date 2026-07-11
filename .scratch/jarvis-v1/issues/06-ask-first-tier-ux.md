# 06 — Ask-first tier UX (voice yes/no + overlay action preview)

Status: done

## What to build

For destructive, out-of-approved-folder, outward-facing, or system-level actions, JARVIS must stop and ask first. Overlay shows the exact proposed action; user confirms or declines by voice ("yes"/"no") with click as backup. Safe-tier behavior from the core loop must remain zero-prompt.

## Acceptance criteria

- [x] Delete/overwrite, out-of-folder, and system-level style actions wait for explicit confirmation
- [x] Overlay previews the exact action being requested
- [x] Voice yes/no completes the gate; click backup works
- [x] Safe-tier actions still auto-run with zero prompts
- [x] Secrets remain untouchable at every tier

## Blocked by

- 02 — Headless core loop
- 05 — Aurora overlay

## User stories covered

12–13, 17, 33

## Comments
