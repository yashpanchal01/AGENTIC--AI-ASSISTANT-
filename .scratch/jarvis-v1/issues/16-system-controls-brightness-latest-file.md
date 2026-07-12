# 16 — System controls: brightness + latest-file resolver

Status: ready-for-agent

## What to build

Two missing everyday verbs. (1) Screen brightness set/step via WMI (`WmiMonitorBrightnessMethods`), with graceful spoken failure on panels/externals that don't support it; "dim brightness to zero" works as a regex reflex and the tool is registered in the router's fixed tool list (issue 14) and the brain bridge (issue 15). (2) A latest-file resolver in the apps/media layer: "open the last screen recording" → newest file in configured capture folders (folders come from settings), opened with the default app. Neither verb needs a confirm gate (non-destructive), but both are audit-logged like every other action.

Why now: the acceptance pack (issue 17) contains "dim my brightness to zero" and "open the screen recording we just captured", and the audit shows no current path can do either — brightness has no handler at all, and file resolution only exists as a generic brain/shell fallback.

## Scope

In: brightness controller + intents (absolute set, step up/down); latest-file resolver + intents; settings keys for capture folders; router tool-list and bridge registration; audit-log entries.
Out: external-monitor DDC/CI control; per-app volume or other new system verbs; content search inside files; confirm-gate changes.

## Acceptance criteria

- [ ] "dim my brightness to zero" / "set brightness to 50" set the panel via WMI on this laptop
- [ ] On a device where WMI brightness is unsupported, JARVIS speaks a plain-language failure (via `plain_replies`), no crash, no silent freeze
- [ ] "open the last screen recording" opens the newest file from the configured capture folder(s); empty/missing folder yields a plain spoken explanation
- [ ] Both tools appear in the router fixed list and the MCP bridge; neither prompts for confirmation; both write audit-log entries
- [ ] Capture folders configurable in the settings file without code edits

## Test plan

- Unit: brightness intent parsing (zero/percent/step), WMI wrapper faked for set + unsupported-panel error paths
- Unit: latest-file resolver with a temp folder tree — newest-by-mtime wins, extension filtering, empty-folder case
- `os_smoke` (opt-in, issue 13's marker): real WMI brightness set-and-restore on this laptop; real open of the newest file in a temp capture folder
- Regression: audit log records both verbs; confirm gate untouched

## Blocked by

- 13 — Land and harden the untracked apps/media/windows slices

## User stories covered

None — backend-audit follow-up (post-v1 architecture)

## Comments
