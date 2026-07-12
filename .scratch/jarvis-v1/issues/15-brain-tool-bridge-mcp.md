# 15 — Tool bridge: give the heavy brain JARVIS's own tools (MCP)

Status: ready-for-agent

## What to build

An MCP server (stdio) that exposes JARVIS's own capabilities as callable tools for the Claude CLI brain: `spotify`, `apps` (open/focus), `windows` (focus/min/max/snap/close), `media`, `memory`, and `google-read`. Register it in the CLI invocation (`jarvis/brain/claude_code.py`) and un-ban those domains in the brain system prompt (`jarvis/config.py:34-42`). Every side-effecting tool call still passes the existing confirm/ask-first gates (`jarvis/confirm.py`, including the secret hard-deny), and every call emits `StepStarted`/`StepFinished`/`StepFailed` on the event bus (issue 12). Grok fallback keeps working exactly as today — without the bridge — and the capability gap is documented in the issue and in the Grok system prompt.

Why now: the audit's problem 1 — the brain is banned from Spotify/apps/windows/media, so any multi-domain request ("open spotify and play the next track") fails even though each half works alone.

Hard constraints: cloud brain = zero local RAM for thinking; the MCP server is a thin stdio process reusing already-loaded JARVIS code, no model weights, negligible footprint inside the ~1 GB budget.

## Scope

In: MCP server module wrapping the existing handlers/controllers; CLI registration; system-prompt un-ban; confirm-gate plumbing through the bridge; Step* emission per tool call; Grok gap documentation.
Out: new tools beyond the six domains listed (brightness/latest-file arrive via issue 16 and plug into this bridge); Grok MCP support; exposing shell/file/web beyond what the CLI already has.

## Acceptance criteria

- [ ] Claude CLI brain can list and call the six JARVIS tools over stdio MCP in a real invocation
- [ ] Brain system prompt no longer forbids Spotify/apps/windows/media; it instructs the brain to prefer JARVIS tools over shell for those domains
- [ ] A side-effecting tool call from the brain triggers the same confirm/ask-first flow as a direct voice command; hard-deny still blocks secrets unconditionally
- [ ] Each bridge tool call emits `StepStarted` and `StepFinished`/`StepFailed` on the bus
- [ ] End-to-end scenario with fakes: "open spotify and play the next track" — brain calls `apps.open` then `spotify.next`, both observed, spoken reply produced
- [ ] Grok provider still answers with today's behavior when selected; its no-bridge limitation is documented

## Test plan

- Unit: MCP tool schemas, dispatch into fake handlers, error mapping to `StepFailed` + `plain_replies`
- Integration: fake brain scripted to issue tool calls through the bridge; asserts confirm gate invoked and bus events ordered Start→Finish per call
- Integration: the two-step Spotify scenario end-to-end with fake Spotify + fake apps
- Regression: Grok path tests unchanged; brain tests with bridge disabled still pass

## Blocked by

- 12 — Typed event bus + live step streaming
- 13 — Land and harden the untracked apps/media/windows slices

## User stories covered

None — backend-audit follow-up (post-v1 architecture)

## Comments
