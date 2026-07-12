# 13 — Land and harden the untracked apps/media/windows slices

Status: ready-for-agent

## What to build

Get the newest slices (`jarvis/apps`, `jarvis/media`, `jarvis/windows` + their tests) commit-ready. Review the code, then add opt-in real-adapter smoke tests behind a pytest marker (`pytest -m os_smoke`) that exercise the real OS paths on demand: actually launch Notepad, snap/minimize/restore its window via `jarvis/windows/win32api.py`, and open a media file. Also clean up config debt found in the audit: delete the dead `grok_safe_tools` key (`jarvis/config.py:108`, never read) and dedupe the safe-tool list currently duplicated between `jarvis/config.py` and `jarvis/brain/grok_cli.py:30`.

Why now: the audit found these slices are entirely uncommitted and the real OS adapters are tested only via injected fakes — nothing has ever proven `win32api.py` or the app-launch path against real Windows except manual use.

Note: the actual `git commit` is done by the human/main session; this issue only defines and verifies readiness.

## Scope

In: code review pass on the three slices; `os_smoke` marker + smoke tests (excluded from the default test run); dead-key deletion; safe-tool list single source of truth.
Out: new features in apps/media/windows; the brightness/latest-file tools (issue 16); router integration (issue 14); the commit itself.

## Acceptance criteria

- [ ] `pytest` (default run) passes with `os_smoke` tests deselected automatically
- [ ] `pytest -m os_smoke` on this machine launches Notepad, snaps/minimizes/restores it, and opens a media file for real, then cleans up (window closed, no orphan processes)
- [ ] `grok_safe_tools` key is gone; settings files containing it still load without error
- [ ] Safe-tool list exists in exactly one place; Grok invocation behavior unchanged
- [ ] A short readiness note in this issue's Comments lists what the review found/fixed, so the human can commit with confidence

## Test plan

- Default suite: green, `os_smoke` skipped (marker registered in pytest config, no warnings)
- Manual gate: run `pytest -m os_smoke` once on this laptop and record results in Comments
- Unit: settings loader tolerates a stale `grok_safe_tools` key in existing `settings.json`
- Regression: existing fakes-based apps/media/windows tests unchanged and green

## Blocked by

None - can start immediately

## User stories covered

None — backend-audit follow-up (post-v1 architecture)

## Comments
