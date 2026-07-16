# JARVIS v1 — issue board (local)

PRD pointer: [PRD.md](./PRD.md) → repo root `PRD-jarvis-v1.md`.

All issues: `Status: ready-for-agent`.

| # | File | Blocked by | Start now? |
|---|------|------------|------------|
| 01 | [issues/01-wake-word-ab-bench.md](./issues/01-wake-word-ab-bench.md) | — | **done-provisional** (bench + pick; full dual mic trials after Picovoice key) |
| 02 | [issues/02-headless-core-loop.md](./issues/02-headless-core-loop.md) | — | yes |
| 03 | [issues/03-mic-whisper-into-loop.md](./issues/03-mic-whisper-into-loop.md) | 02 | |
| 04 | [issues/04-wake-word-and-hotkey-front-doors.md](./issues/04-wake-word-and-hotkey-front-doors.md) | 01, 03 | |
| 05 | [issues/05-aurora-overlay-states.md](./issues/05-aurora-overlay-states.md) | 04 | |
| 06 | [issues/06-ask-first-tier-ux.md](./issues/06-ask-first-tier-ux.md) | 02, 05 | |
| 07 | [issues/07-markdown-long-term-memory.md](./issues/07-markdown-long-term-memory.md) | 02 | after 02 |
| 08 | [issues/08-google-oauth-gmail-calendar.md](./issues/08-google-oauth-gmail-calendar.md) | 02 | **done** |
| 09 | [issues/09-spotify-voice-control.md](./issues/09-spotify-voice-control.md) | 02 | after 02 |
| 10 | [issues/10-long-running-tasks.md](./issues/10-long-running-tasks.md) | 02, 05 | |
| 11 | [issues/11-ship-polish-lifecycle.md](./issues/11-ship-polish-lifecycle.md) | 04, 05 | |
| 12 | [issues/12-event-bus-step-streaming.md](./issues/12-event-bus-step-streaming.md) | — | yes |
| 13 | [issues/13-land-untracked-slices.md](./issues/13-land-untracked-slices.md) | — | yes |
| 14 | [issues/14-local-router-ollama.md](./issues/14-local-router-ollama.md) | 13 | |
| 15 | [issues/15-brain-tool-bridge-mcp.md](./issues/15-brain-tool-bridge-mcp.md) | 12, 13 | |
| 16 | [issues/16-system-controls-brightness-latest-file.md](./issues/16-system-controls-brightness-latest-file.md) | 13 | |
| 17 | [issues/17-acceptance-pack-canonical-tasks.md](./issues/17-acceptance-pack-canonical-tasks.md) | 14, 15, 16 | |
| 18 | [issues/18-spine-overlay-port.md](./issues/18-spine-overlay-port.md) | 12, 15, 17 | **last** |
| 19 | [issues/19-perception-tools.md](./issues/19-perception-tools.md) | — | yes |
| 20 | [issues/20-conversation-context.md](./issues/20-conversation-context.md) | — | yes |
| 21 | [issues/21-gated-shell-file-tools.md](./issues/21-gated-shell-file-tools.md) | 19 | |
| 22 | [issues/22-grok-tool-bridge.md](./issues/22-grok-tool-bridge.md) | 21 | |
| 23 | [issues/23-fault-event-breadth.md](./issues/23-fault-event-breadth.md) | — | **last** (catches 19/21/22 failure sources for free) |

## Next

Fresh session per issue → `/implement` with the PRD + one issue file.  
v1 wave (01–11): unblocked were **01** and **02**.  
v1.1 wave (12–18, from the backend audit): done (14 shelved).  
v1.2 wave (19–23, "make it smart"): perception → context → gated hands → fault polish → Grok parity. Build order: **19**, **20** (either order) → **21** → **23** → **22** last (user hold 2026-07-16: start 22 only on their explicit go).
