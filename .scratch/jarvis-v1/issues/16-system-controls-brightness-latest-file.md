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

### 2026-07-13 — implemented (agent, left in tree for review; not committed)

New slice `jarvis/system/` (brightness + latest-capture), wired as a reflex handler
and an MCP bridge tool. Summary:

- **Brightness impl choice:** PowerShell CIM subprocess (`Get-CimInstance` /
  `Invoke-CimMethod` over `root/wmi`, `WmiSetBrightness`), not hand-rolled COM
  through ctypes. Rationale: WMI brightness is COM-only; hand-rolling IWbem via
  ctypes for one setter is fragile, and `pywin32`/`wmi` are exactly the heavy deps
  this repo avoids (it built `windows/win32api.py` on ctypes and Google on stdlib
  urllib). `subprocess` is stdlib → dependency-free, robust. Real calls isolated
  behind `default_get_brightness` / `default_set_brightness` (fakeable).
- **Graceful failure:** unsupported panels/externals → `BrightnessError` caught in
  the handler → speaks `plain_replies.BRIGHTNESS_UNSUPPORTED` (new code
  `brightness_unsupported`), `ok=False`, no crash/freeze. os_smoke skips (not fails)
  on unsupported devices.
- **Registration (per spec correction — issue-14 router is shelved/not on main):**
  (1) reflex — new `system=` handler param on `handle_command`, dispatched before
  the brain (mirrors apps/windows/media), threaded through cli/voice/wake/overlay;
  (2) MCP bridge — new `system` tool in `mcp_bridge._TOOLS` + `system` field.
  Neither verb trips the confirm gate (non-destructive; not risky/secret), so the
  bridge tool runs un-gated and still emits StepStarted→StepFinished/StepFailed.
- **Latest-file:** `find_latest` = newest-by-mtime in `config.capture_folders`,
  video-ext filtered; opened via the media slice's real `default_open`. Empty/
  missing folder → plain spoken "couldn't find…". Capture folders come from the new
  `capture_folders` SETTINGS key / `JARVIS_CAPTURE_FOLDERS` env (default
  `~/Videos/Captures`, `~/Videos`) — configurable without code edits.
- **Audit:** both verbs flow through `handle_command` → `_audit_result(path="system")`.
- **Tests:** default suite 284→314 passing (+29 unit in `test_system_controls.py`,
  +1 bridge test; updated two bridge tests that hard-coded "six tools"). os_smoke
  now 4 tests — ran the two new ones on this laptop: real WMI set-and-restore PASS
  (captured original, set mild value, asserted, restored) and real newest-capture
  open+close in a temp folder PASS.
- **Acceptance:** all 5 criteria met (brightness set via WMI ✓, unsupported→plain ✓,
  latest recording + empty-folder plain ✓, both in bridge + no confirm + audited ✓,
  capture folders in settings ✓). Deviation: none functionally; router-list item
  reinterpreted as the reflex handler per the spec correction.
- **Bug fixed mid-build:** unescaped `{` in the PS set-template (`.format`) — real
  calls raised ValueError; switched to `__LEVEL__` `str.replace`. Caught by os_smoke.
