# 18 — Port the MK.I SPINE overlay onto the event bus (LAST)

Status: ready-for-agent

## What to build

A new `Overlay` implementation that ports the MK.I SPINE prototype (`C:\tmp\overlay-proto\jarvis_overlay_spine_locked.py`) onto the issue-12 event bus, mapping bus events to its surfaces:

| SPINE surface | Bus event |
|---------------|-----------|
| step ledger | `StepStarted` / `StepFinished` / `StepFailed` |
| thought ticker | `TokenTick` |
| brain readout | `BrainSelected` |
| fault state | `Fault` / `StepFailed` |
| commit ring | `ConfirmRequested` |
| green success pulse | `TaskCompleted(ok)` |

Aurora remains the default; SPINE is selected via settings. **This issue is LAST — start only after the backend issues (12–17) have landed**, because without the tool bridge and router there are no real step/brain events for it to render.

Why now (then): the audit's problem 3 — the brain does multi-step work invisibly; once issue 12 streams steps and 15 makes the brain call JARVIS tools, the UI can finally show what JARVIS is doing while it does it.

Hard constraints: overlay stays lightweight (same order of footprint as Aurora) inside the ~1 GB resident budget; rendering must never block the command pipeline (bus subscribers are already isolated per issue 12).

## Scope

In: SPINE overlay class implementing the `Overlay` protocol + bus subscription; settings switch aurora/spine; event→surface mapping above; graceful idle/wake/sleep states matching the existing lifecycle.
Out: changes to the bus or event types; changes to Aurora; new backend behavior; redesigning the prototype's visuals (port, don't reinvent).

## Acceptance criteria

- [ ] SPINE overlay runs as a drop-in `Overlay` implementation, selected via the settings file, Aurora untouched as default
- [ ] Fake-bus replay of a scripted brain session renders: steps appearing/completing in the ledger, ticker advancing on `TokenTick`, brain name shown on `BrainSelected`
- [ ] `ConfirmRequested` shows the commit ring until the confirm flow resolves; `Fault`/`StepFailed` shows the fault state; `TaskCompleted(ok)` fires the green pulse
- [ ] Overlay process/thread survives malformed or out-of-order events without crashing the pipeline
- [ ] Live run on this laptop with a real brain call shows steps streaming during the call, not after

## Test plan

- Unit: event→surface mapping with a headless/fake renderer (no GUI needed in CI)
- Integration: replay a recorded event trace from issue 12's fixtures; assert surface state transitions
- Manual: side-by-side sanity run vs Aurora on this laptop; check RAM footprint and record in Comments

## Blocked by

- 12 — Typed event bus + live step streaming
- 15 — Tool bridge (MCP)
- 17 — Acceptance pack (backend behavior frozen before the UI ports onto it)

## User stories covered

None — backend-audit follow-up (post-v1 architecture)

## Comments

### 2026-07-13 — SPINE overlay ported onto the event bus

Landed the MK.I SPINE overlay as a drop-in `Overlay` implementation. Aurora is
untouched and stays the default.

Files added:
- `jarvis/overlay/spine_surface.py` — headless data model (no Qt): `SpineSurface`
  + `SpineStep`/`SpineSnapshot` + `SpineSubscriber`. All event -> surface mapping
  lives here so it is unit-testable with no display.
- `jarvis/overlay/spine.py` — Qt widget `SpineOverlay` (ports the prototype's
  paintEvent/easing/scramble/instruments), marshals bus/worker events to the UI
  thread via Qt signals (Aurora pattern), renders from a `SpineSnapshot`.
- `tests/test_spine_overlay.py` — 17 tests (unit mapping + scripted-trace
  integration + malformed/out-of-order robustness + Qt paint + offscreen GUI
  smoke subprocess).

Files changed:
- `jarvis/config.py` — new `overlay_style` field ("aurora" default | "spine") +
  `JARVIS_OVERLAY_STYLE` env override.
- `jarvis/settings.py` — `overlay_style` settings key (validated aurora/spine).
- `jarvis/cli.py` — `_run_with_qt_overlay` selects Aurora vs SPINE by
  `overlay_style`; SPINE also `attach_events(bus)` for the rich instrument feed
  (StateChanged still flows via the shared `attach_overlay` -> `set_state` path).

Event -> surface wiring: StepStarted/Finished/Failed -> step ledger;
TokenTick -> thought ticker/odometer; BrainSelected -> brain readout;
Fault/StepFailed -> latched fault (red FLT LED + FAULT plate flash + glitch-cut);
ConfirmRequested (or CONFIRM state) -> commit ring, cleared when the confirm
resolves (leaves CONFIRM) or the task completes; TaskCompleted(ok=True) -> green
success pulse. REST hides the plate (fade out), HEARD begins a fresh turn
(clears the previous ledger + fault latch + ticker).

Acceptance: all 5 criteria met except #5 (live real-brain run) which is a MANUAL
check left for the user — NOT run here to avoid burning Claude usage.

Manual live-run command (set the switch, then speak a multi-step command):
```
setx JARVIS_OVERLAY_STYLE spine
# new shell, then:
py -3.13 -m jarvis --daemon
# say: "jarvis, play my focus mix and log the gpu temps"
```
(or add `"overlay_style": "spine"` to `~/.jarvis/settings.json`). Steps should
appear in the ledger and the ticker advance DURING the call, not after.

Tests: 359 -> 376 (default suite green, quota-safe). GUI smoke: offscreen
subprocess drives a full fake trace, prints `SMOKE OK`, exits 0, zero QPainter
warnings on stderr. RAM: SPINE ~62.1 MB vs Aurora ~61.4 MB resident with a
WORKING frame painted (+0.7 MB — same order, well within the ~1 GB budget).

Deviations/flags:
- The prototype's mic privacy-shutter and per-step arming-countdown are ported
  as machinery but there is no production event to drive mic-mute, so the
  shutter stays open; the ask-first commit ring is driven by ConfirmRequested
  instead of the demo's scripted arm countdown.
- `Fault` is defined in the event vocabulary but not currently published by any
  producer (only StepFailed is); both are wired to the fault surface so it lights
  up if/when `Fault` is emitted.
- The ledger is dynamic (real step names/badges), not the prototype's fixed
  5-step script; tool badges are derived from the live step name.
