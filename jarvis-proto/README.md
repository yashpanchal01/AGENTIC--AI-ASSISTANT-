# jarvis-proto — PROTOTYPE, throwaway

**Question this answers:** Can headless Claude Code (`claude -p` with pre-approved
permission flags) act as JARVIS's brain — executing real commands (launch apps,
file operations, questions) with **zero permission prompts** — and what is the
honest end-to-end latency per command?

**Not** part of this prototype: voice, wake word, TTS, integrations. Text in,
timed result out.

## Run

```powershell
node "C:\Users\YASH PANCHAL\NEW_project\jarvis-proto\jarvis-tui.mjs"
```

Type a command as if speaking to JARVIS (e.g. `open notepad`, `what time is it`,
`create a file called hello.txt with a haiku in it`). Special keys:

- `:m` — cycle model (haiku → sonnet → default) to compare latency
- `:q` — quit

One-shot mode (prints JSON timing report):

```powershell
node jarvis-tui.mjs --once "open notepad"
```

## Files

- `brain.mjs` — the portable bit: spawns headless claude, streams events, returns timings. This is the module a real JARVIS would lift.
- `jarvis-tui.mjs` — throwaway terminal shell around it.
- `NOTES.md` — verdict goes here before this folder is deleted.
