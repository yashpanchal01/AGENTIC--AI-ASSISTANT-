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

### 2026-07-13 — implemented (agent)

**Transport: Option A (in-process HTTP MCP server).** JARVIS hosts a Streamable-HTTP
MCP server *inside its own process* (`jarvis/brain/mcp_bridge.py`, hand-rolled on
`http.server` + stdlib `json` — no `mcp` SDK dependency, consistent with the repo's
stdlib style) bound to `127.0.0.1:<ephemeral>`, and registers it with the Claude CLI by
URL via `--mcp-config '{"mcpServers":{"jarvis":{"type":"http","url":".../mcp"}}}'`.
Chosen over Option B (stdio proxy + IPC) because the spec's stdio server is spawned as
the CLI's *own* child process with no shared memory — it could not touch JARVIS's live
confirmer or in-process `EventBus`. **With Option A the confirm gate and Step* events do
not cross a process boundary at all:** every `tools/call` runs on JARVIS's own threads
with direct references to the real handlers, the real `Confirmer`, and the real bus. No
IPC, no serialization, nothing stubbed.

**Safety gate.** Every side-effecting call goes through `jarvis/confirm.py` **unchanged**:
`is_secret_request` → hard-deny (handler never runs); `is_risky_request` → ask-first via
the injected confirmer (decline/`None` confirmer ⇒ never runs). Plus a *bridge-scoped*
tightening (`_BRIDGE_EXTRA_RISKY = close|forget`) that ADDS confirmation for the two
destructive domain verbs the generic word-list misses — window **close** (task explicitly
requires it) and memory **forget**. This only strengthens; it never weakens confirm.py and
does not touch the voice path.

**Bus.** Each call emits `StepStarted` then `StepFinished` (ok) or `StepFailed`
(secret/decline/handler-error/unhandled), errors mapped through `plain_replies`.

**System prompt** (`jarvis/config.py`): removed the Spotify/media "handled by JARVIS
itself" bans; base now un-bans those domains and keeps the Gmail/Calendar *write* refusal
+ "never fake success". Claude gets `CLAUDE_TOOL_BRIDGE_GUIDANCE` (prefer the six tools
over shell) only when the bridge is active. Grok gets `GROK_NO_TOOL_BRIDGE_NOTE`
documenting that it lacks the bridge (capability gap) — Grok is otherwise unchanged and
bridge-less.

**Scenario proof:** `tests/test_mcp_bridge_scenario.py` drives a fake brain (scripted to
call `apps` then `spotify`) through `core.handle_command`; asserts Spotify launched, the
next-track fired, bus events ordered StepStarted/Finished(apps) → StepStarted/Finished(spotify),
and a spoken reply. A real MCP handshake (`initialize`/`tools/list`/`tools/call`) is proven
against the live server with a urllib client in `tests/test_mcp_bridge_handshake.py`.

**Deviations / flags:**
- Literal "stdio" is deviated from (Option A HTTP) — deliberate, per the crux; documented above.
- The real-`claude` end-to-end test is gated behind the opt-in `claude_live` marker
  (`tests/test_mcp_bridge_live.py`), deselected by default so CI never burns Claude usage.
  It was **not executed** here to avoid burning the user's quota; the server's MCP
  conformance is instead verified against a compliant urllib client. Run with
  `py -3.13 -m pytest -m claude_live`.
- Pre-existing hazard (not introduced here): `tests/test_smoke_claude.py` (marker `smoke`)
  is still collected by default and calls the real Claude CLI when `claude` is on PATH.
  Left as-is to preserve the documented baseline count; consider adding `smoke` to the
  default deselect list if CI has `claude` installed.
