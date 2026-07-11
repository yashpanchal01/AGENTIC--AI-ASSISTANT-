# 11 — Ship polish: settings, approved folders, autostart, tray, audit log, offline brain

Status: ready-for-agent

## What to build

Production lifecycle and trust surfaces: simple settings file (hotkey, approved folders, voice preferences); configure which folders are autonomous-safe; start with Windows; warm the brain at startup to avoid first-command cold start; system tray icon with pause/quit; audit log of every action; plain-language spoken errors; when internet/brain is unreachable, say so while local wake/STT/TTS still work.

## Acceptance criteria

- [ ] Settings file controls hotkey, approved folders, and voice without code edits
- [ ] Autostart with Windows works; brain warm-up reduces first-command cold start
- [ ] Tray icon shows alive state and supports pause/quit
- [ ] Audit log records actions with enough detail to review later
- [ ] Offline/unreachable brain yields a spoken explanation; local ears/voice still function
- [ ] Errors are spoken in plain language, not silent freezes

## Blocked by

- 04 — Wake word + hotkey front doors
- 05 — Aurora overlay

## User stories covered

35–36, 50–56 (errors 54–55 as needed)

## Comments
