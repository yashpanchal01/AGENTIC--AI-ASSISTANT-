# 22 — Grok tool bridge: the free fallback learns to act

Status: ready-for-agent

## What to build

Wire `GrokCliBrain` to the existing HTTP MCP bridge so the fallback brain can act, not just talk. Today Grok runs with `GROK_NO_TOOL_BRIDGE_NOTE` in its prompt (honest about being handless) — this issue removes that gap. It matters because the user hits Claude usage limits constantly; when Claude is out, JARVIS currently degrades to a chatbot.

**Step 0 is a capability probe, not code:** determine whether the installed Grok CLI supports MCP servers (`grok --help`, docs, a scratch session with a config pointing at a live bridge). The bridge is Streamable HTTP on localhost (issue 15 chose HTTP precisely so it is "reusable across CLIs") — if Grok takes an MCP config with a URL-type server, this issue is mostly plumbing:

- Pass the bridge's MCP config to Grok the way `claude_code.py` does (`--mcp-config` equivalent).
- Restrict Grok's tool surface to bridge tools. Known 2026-07 gotcha (documented in `grok_cli.py`): `--tools` allowlist and `--disallowed-tools` both break session create — re-test with MCP attached; if the allowlist still breaks, keep default tools but make the system prompt direct Grok to prefer `mcp__jarvis__*` tools, and rely on the bridge's in-process confirm/deny for everything that matters. NOTE: Grok runs `--always-approve` with its own `run_terminal_cmd` — with issue 21 landed, decide whether Grok's native shell must be neutered harder (prompt ban + post-hoc audit of its JSON action log) and record the decision.
- Delete `GROK_NO_TOOL_BRIDGE_NOTE` and update the capability text.
- Bus events: bridge tool calls already emit steps regardless of caller — verify SPINE lights up on a Grok turn.

**If the probe fails** (no MCP support in Grok CLI): implement nothing speculative. Record the finding in this file's Comments with the exact CLI version and failing invocation (the Gemini dead-end pattern), file the fallback idea (prompt-based JSON action protocol) as a note, and close the issue as blocked-external.

## Scope

In: capability probe, MCP config plumbing for Grok, tool-surface restriction (or documented prompt-level mitigation), removal of the no-bridge note, parity tests with fakes.
Out: making Grok the default (Claude stays default); Grok-specific tools; the JSON-action-protocol fallback (separate issue if ever needed); automatic Claude→Grok failover on usage-limit errors (worth a future issue — note it, don't build it).

## Acceptance criteria

- [ ] Probe result recorded in Comments: Grok CLI version + MCP support yes/no + exact invocation
- [ ] (If supported) `JARVIS_BRAIN=grok` + "open spotify and play the next track" → real actions via bridge tools, confirm gate intact, steps on the bus
- [ ] (If supported) Destructive request via Grok hits the same in-process confirm/hard-deny as via Claude — test proves caller-independence
- [ ] `GROK_NO_TOOL_BRIDGE_NOTE` gone; prompt no longer claims Grok cannot act
- [ ] Suite green + quota-safe (no real Grok/Claude calls in default run; args-inspection fakes)

## Test plan

- Unit: `_build_args` includes the MCP config; fake CLI asserts the config JSON shape
- Unit: bridge accepts a second concurrent client session (Claude + Grok configured simultaneously)
- Integration: fake Grok transcript with a bridge tool call → confirm gate exercised, audit written
- Manual (documented in Comments, not CI): one real Grok turn on this laptop moving Spotify or a window

## Blocked by

- 21 — gated shell + file tools (Grok inherits the full, hardened tool surface; the always-approve/native-shell decision needs 21's policy to exist)

## User stories covered

None — v1.2 "make it smart" wave (Claude-usage-limit resilience)
