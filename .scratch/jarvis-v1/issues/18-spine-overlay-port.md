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
