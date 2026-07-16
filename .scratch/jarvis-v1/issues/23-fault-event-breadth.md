# 23 — Fault breadth: reflex and offline failures flash the overlay too

Status: ready-for-agent

## What to build

Today `Fault` fires only at the brain-turn `result` boundary (issue 18 follow-up, commit 6c025c5), so a failed reflex — brightness unsupported, app didn't launch, media file not found — *speaks* the error but the overlay stays calm. The user's rule: every visual element encodes real data; a spoken failure with a green-ish overlay is a lie of omission. Broaden `Fault` so any failed command turn flashes SPINE red, whatever tier failed.

Design constraints (this was deferred before because of these — solve them, don't sidestep):

- **Single-fire rule:** exactly one `Fault` per failed turn. The brain path already publishes at its result boundary; if the bus is threaded into `core.handle_command`, a brain failure must not fire twice (once in core, once in the brain wrapper). Cleanest shape: hoist fault publication to ONE seam — the same place `_audit_result` sees every tier's outcome — and REMOVE the brain-path publisher, so all tiers share one publication point. Keep the semantic: fault on the turn's final outcome, not on mid-turn `StepFailed` (a step can fail and the turn still recover).
- **What counts as a fault:** `ok=False` outcomes. Deliberate non-actions do NOT flash: confirm-declined ("no"), secret-tier refusal, hard-deny, "not set up yet" pointers (Spotify/Google unconfigured) — those are JARVIS working correctly. A settings-free heuristic is fine (denied/needs_confirmation/unconfigured codes excluded; honest failures like `brightness_unsupported`, `app_launch_failed`, `not_found` included). Enumerate the classification in one function with a unit-test table.
- **Offline tier included:** offline/connectivity failures route through the same seam.
- `tasks.py` long-running turns: the completion path already pulses green on success; wire the failure path to the same fault seam (no double-fire with the brain wrapper — covered by the hoist).

## Scope

In: one fault-publication seam covering reflex/offline/brain/long-task outcomes, fault classification function, removal of the now-redundant brain-boundary publisher, tests.
Out: new overlay visuals (SPINE's fault surface exists and works); per-step mid-turn faults; retry logic; changing spoken error text.

## Acceptance criteria

- [ ] "set brightness to zero" on an unsupported panel → spoken failure AND one `Fault` on the bus (SPINE flashes red)
- [ ] App-launch honest failure (window never appeared) → one `Fault`
- [ ] Brain-turn failure still produces exactly ONE `Fault` (regression: no double-fire after the hoist)
- [ ] Confirm-declined, secret refusal, hard-deny, "Spotify not set up" → NO `Fault`
- [ ] `TaskCompleted` green pulse on success unchanged; long-task failure faults once
- [ ] Suite green; bus-event assertions added to existing tier tests rather than a parallel test file where practical

## Test plan

- Unit: classification table (ok/denied/needs_confirmation/unconfigured/honest-failure codes → fault yes/no)
- Unit: bus capture around `handle_command` per tier (fake adapters forced to fail) — exactly one Fault each
- Regression: brain success path, green pulse, ledger ordering (Fault after the tier's StepFailed, before idle)
- Manual: `JARVIS_OVERLAY_STYLE` default SPINE, real "set brightness to 200 percent"-class failure, observe one red flash

## Blocked by

— (independent; can land any time, but schedule LAST — issues 19/21/22 all add new failure sources this seam should catch for free)

## User stories covered

None — v1.2 polish debt (deferred from issue 18 wiring, commit 6c025c5)

## Comments

### 2026-07-16 — implemented (agent, left in tree for review; not committed)

Fault publication hoisted to the one seam where every tier's outcome already
lands — the same `_audit_result` helper that issue 20's `_record_dialogue`
rides — and the brain-boundary publisher removed. Summary:

- **One classification point:** `jarvis.core.should_fault(result)` +
  `_NON_FAULT_ERRORS`. Honest `ok=False` failures fault
  (`brightness_unsupported`, `no_window`/`not_running`, `not_found`,
  timeouts, `brain_unreachable`/`spotify_unreachable`/`google_unreachable`,
  `rate_limited`, exception names, unknown codes — fail-visible default).
  Deliberate non-actions never fault: `denied=True` (secret/hard-deny),
  `confirmation_declined`/`confirmation_incomplete`, `cancelled`, `busy`,
  `already_finished`, `not_configured`/`not_signed_in` setup pointers,
  `empty_transcript`. Unit-test table in `tests/test_handle_command.py`.
- **One publication point:** `jarvis.core.publish_fault(bus, result)` fires
  from `_audit_result` (all reflex/google/spotify/offline/brain/long-task
  returns) plus one explicit call on the confirm-gate return — the exact
  `_record_dialogue` pattern. `handle_confirmation`'s internal audit stays
  bus-less so confirm results fault once, at the caller.
- **Brain publisher removed:** `StreamParseState.ingest` no longer emits
  `Fault` on a failed `result` (6c025c5 relocated); `TaskCompleted(ok=False)`
  unchanged. Regression test drives a scripted failing CLI through the full
  `handle_command` path: `StepStarted → StepFailed → TaskCompleted → Fault`,
  exactly one Fault — mid-turn `StepFailed` (incl. issue 19/21 bridge tools)
  never faults, only the turn's final outcome.
- **Long tasks:** foreground failures fault through the core seam like any
  turn; a BACKGROUNDED turn's final failure publishes once from
  `_watch_and_announce` (next to the `task_failed` audit) via the same
  classifier — the "On it." ack is ok=True so the core seam stays silent.
  Green `TaskCompleted` pulse untouched.
- **Plumbing:** `bus=` threaded as an optional kwarg alongside `audit=`:
  `handle_command`, `LongTaskService.handle_brain`, `voice.listen_and_handle`,
  `overlay/lifecycle` (both wrappers), `wake/pipeline.run_armed_pipeline`,
  `FrontDoorSession` (new field), and `cli.py`
  (run_once/run_listen/run_repl/run_daemon + all `main()` call sites) — so
  the resident daemon, --listen, --once, and the REPL all fault for real.

Verified live (no mocks on the seam): fake adapters forced to fail produced
exactly one `Fault` each for brightness-unsupported, app-launch no-window,
offline `brain_unreachable`, failed brain turn, and backgrounded long-task
failure; secret deny / declined confirm / Spotify "not set up" / success
produced zero. SPINE offscreen smoke (`JARVIS_SPINE_SMOKE=1`,
`run_spine_smoke`) exits 0: "SMOKE OK: MK.I SPINE drove a full event trace
clean". Suite: 540 passed, 15 deselected (baseline 511 + 29 new, all green).
