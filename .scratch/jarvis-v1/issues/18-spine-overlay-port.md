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

### 2026-07-13 — Wired the three dormant surfaces to real signals

Follow-up: the three surfaces that were ported as machinery with no producer now
encode REAL data (no decorative/fake animation).

1. **Fault publisher.** Producer added at the terminal `result` boundary in
   `jarvis/brain/stream_json.py`: when a brain turn ends not-ok (error subtype /
   `error` field / rate-limit), it emits `TaskCompleted(ok=False)` **and** a
   single `Fault`. This is the exact failure counterpart of the green success
   pulse (`TaskCompleted(ok=True)`), at the same command/task-level boundary —
   distinct from a mid-task `StepFailed`: a tool step can fail and the turn still
   recover to ok=True, in which case NO Fault fires (verified by test). One
   `result` per turn ⇒ at most one Fault ⇒ no double-firing. This covers the
   Claude brain path (the only producer of the success pulse too); command-level
   errors outside a Claude turn (offline pre-check, exceptions) keep their
   existing plain-spoken error path and are deliberately not re-published as
   Fault to avoid noise.

2. **Mic privacy-shutter.** New minimal event `ListeningChanged(listening: bool)`
   in `jarvis/events.py`. `cli.py` wires `ResidentController.on_state_change` to
   publish it on the shared bus (paused ⇒ `listening=False`; running ⇒ True) —
   the tray keeps wrapping the same hook, so both fire. The SPINE surface tracks
   `mic_muted`; the widget drives `self.shutter` closed (red) while not
   listening and open while listening. Because the daemon idles at REST (plate
   hidden), the plate now also *reveals* while muted so the closed shutter is
   actually visible, with a "muted — not listening" transcript hint.

3. **Arm-countdown / commit ring.** No code change: the port has a single
   arming surface — the commit ring — already driven by the real
   `ConfirmRequested` and resolved when the confirm flow leaves CONFIRM or the
   turn completes (`TaskCompleted`). There is no separate dormant arm-countdown
   or fabricated timer to drive or hide; the prototype's per-step arm-countdown
   was folded into the commit ring at the original port. The ring's rotating
   sweep is an indeterminate "awaiting your yes/no" spinner gated on the real
   pending-confirm state, not a countdown-to-auto-commit. Confirmed + covered by
   existing tests (`test_confirm_requested_shows_ring_until_resolved`,
   `test_task_completed_resolves_pending_ring`).

Files changed:
- `jarvis/events.py` — add `ListeningChanged` event (+ `__all__`).
- `jarvis/brain/stream_json.py` — emit `Fault` on a not-ok terminal `result`.
- `jarvis/overlay/spine_surface.py` — `mic_muted` state + `ListeningChanged`
  handler + snapshot field + mapping-table doc.
- `jarvis/overlay/spine.py` — drive `self.shutter` from `mic_muted`, reveal the
  plate while muted, muted transcript hint, mute/unmute in the GUI smoke trace.
- `jarvis/cli.py` — publish `ListeningChanged` from `resident.on_state_change`.
- `tests/test_step_streaming.py` — Fault emitted on failed result; recovered
  StepFailure emits NO Fault; failing Claude turn publishes one Fault on the bus.
- `tests/test_spine_overlay.py` — `ListeningChanged` drives `mic_muted`; mute is
  turn-independent; resident-pause→bus→surface integration; widget shutter
  closes/reveals then reopens.

Tests: 376 → 383 (default suite green, quota-safe — no real Claude calls). GUI
smoke: offscreen subprocess drives the fake trace incl. mute/unmute, prints
`SMOKE OK`, exits 0, zero QPainter warnings.

Deviations/flags:
- Rate-limited turns now latch the fault surface (they end ok=False) — correct,
  a usage-limit hit is a real failure.
- Fault scope is intentionally the Claude brain-turn boundary (symmetric with
  the success pulse), not every possible command-level failure; broadening to
  offline/exception paths would need the bus threaded into `core`/`tasks` and
  risks double-firing, so it was left out per "stay minimal / avoid noise".
