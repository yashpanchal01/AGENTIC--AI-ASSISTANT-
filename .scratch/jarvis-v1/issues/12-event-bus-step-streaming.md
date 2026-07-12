# 12 — Typed event bus + live step streaming

Status: ready-for-agent

## What to build

A small in-process pub/sub bus with typed events: `StateChanged`, `TranscriptPartial`, `TranscriptFinal`, `StepStarted`, `StepFinished`, `StepFailed`, `TokenTick`, `BrainSelected`, `ConfirmRequested`, `Fault`, `TaskCompleted`. The existing `Overlay` protocol (`jarvis/overlay/base.py`) becomes just one subscriber: an adapter maps events → `set_state`, with zero behavior change for Aurora. The brain CLI stream (`jarvis/brain/stream_json.py` already parses Claude stream-json) is turned into `StepStarted`/`StepFinished`/`TokenTick` events **live during the call**, not summarized at the end. The audit log (`jarvis/audit.py`) also subscribes — same records as today, no behavior change.

Why now: the backend audit found the overlay only receives coarse `set_state` through a single-subscriber protocol, so brain tool-steps never reach the UI; the bus is also the prerequisite for the tool bridge (15) and the SPINE overlay (18).

Hard constraints: pure in-process (no sockets, no threads beyond what exists), negligible RAM — total resident budget stays ~1 GB alongside LocalFlow.

## Scope

In: bus module + event types; overlay adapter subscriber; audit subscriber; live event emission from the Claude stream-json parse path; Grok path emits at least `StepStarted`/`StepFinished` per tool call it reports.
Out: any new UI (that is issue 18); changing what Aurora displays; MCP tools (issue 15); persisting events anywhere except the existing audit log.

## Acceptance criteria

- [ ] All existing tests stay green with the overlay driven through the bus adapter
- [ ] A fake subscriber test proves `StepStarted`/`StepFinished`/`TokenTick` fire **during** a (fake) brain call, not after it returns
- [ ] Aurora overlay behavior is byte-for-byte unchanged (same `set_state` sequence for the same scenario)
- [ ] Audit log output for a scripted session is unchanged after switching it to a bus subscription
- [ ] Multiple subscribers can attach; a slow/broken subscriber cannot crash or block command handling

## Test plan

- Unit: publish/subscribe ordering, unsubscribe, exception isolation per subscriber
- Unit: stream-json fixture replayed through the parser asserts the exact event sequence emitted
- Integration: fake brain + fake subscriber records events with timestamps interleaved inside the call window
- Regression: existing overlay + audit test suites, unmodified

## Blocked by

None - can start immediately

## User stories covered

None — backend-audit follow-up (post-v1 architecture)

## Comments
