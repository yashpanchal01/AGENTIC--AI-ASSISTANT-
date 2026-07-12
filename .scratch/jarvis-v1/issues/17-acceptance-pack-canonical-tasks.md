# 17 — Acceptance pack: canonical complex tasks, end-to-end

Status: ready-for-agent

## What to build

The user's five canonical tasks as checked-in end-to-end tests — fakes wherever OS/cloud is involved, plus `os_smoke`-marked real variants where meaningful. Each test declares which tier must handle it and asserts a max-latency budget for that tier's dispatch:

| Task | Expected tier |
|------|---------------|
| (a) "open the screen recording we just captured" | router → latest-file tool (16) |
| (b) "open spotify and play the next music" | brain + tool bridge (15), two steps |
| (c) "close all the windows" → **minimize** all | router idiom (14), windows handler |
| (d) "dim my brightness to zero" | reflex (16) |
| (e) "open brave and vs code side by side, brave left 50%, vs code right" | brain + bridge: launch both, wait for windows, snap left/right |

Why now: the audit showed every one of these currently fails or falls into a 300s-class CLI call; this pack pins the target behavior so the router/bridge work is finished when these pass, and guards against regressions after.

Latency budgets (dispatch decision + local handler, fakes for cloud/OS): reflex < 1s; router path < 3s (2s router cap + handler); brain path may exceed the ~20s long-task threshold only via the existing backgrounded "on it" flow — never a silent stall.

## Scope

In: five e2e tests with fakes; tier + latency assertions; `os_smoke` real variants for (a), (c), (d); a small harness helper to run an utterance through the full reflex→router→brain pipeline with fakes injected.
Out: new features (all functionality comes from 14–16); UI assertions (issue 18); benchmark tooling beyond simple wall-clock asserts.

## Acceptance criteria

- [ ] All five tasks pass end-to-end with fakes, each handled by its declared tier (a test fails if the wrong tier answers)
- [ ] (c) minimizes windows — a test explicitly asserts no app/process is closed
- [ ] (e) with fakes: both launches issued, window-wait observed, left/right snap calls made in order
- [ ] Latency assertions enforced per tier as budgeted above
- [ ] `pytest -m os_smoke` variants for (a), (c), (d) pass on this laptop
- [ ] Pack runs in the default suite (fakes) in well under a minute

## Test plan

- The pack **is** the test plan: one test module per task, parameterized over tier expectation + budget
- Router-dependent tests reuse issue 14's skip logic when Ollama is absent (fake router responses keep the pipeline tests running everywhere)
- Manual: run the `os_smoke` variants once on this laptop and record timings in Comments

## Blocked by

- 14 — Local router tier (Ollama)
- 15 — Tool bridge (MCP)
- 16 — System controls: brightness + latest-file resolver

## User stories covered

None — backend-audit follow-up; encodes the user's canonical tasks (a)–(e)

## Comments
