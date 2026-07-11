# JARVIS v1

Windows-first, voice-driven AI assistant. This repo currently ships the
**headless core loop** (issue 02): typed text → persistent tiered brain → act →
Piper reply. No overlay yet.

## Requirements

- Windows 11
- Python **3.13** via `py -3.13`
- [Claude Code](https://claude.ai/code) CLI on `PATH` (for the real brain)
- Optional: [Piper](https://github.com/rhasspy/piper) binary + ONNX voice for spoken replies

## Setup

```powershell
cd NEW_project
py -3.13 -m pip install -e ".[dev]"
```

Voice model (already on this machine if present):

- `~/Downloads/en_GB-northern_english_male-medium.onnx`
- Download the matching `.onnx.json` next to it from
  [piper-voices](https://huggingface.co/rhasspy/piper-voices)
- Install the Piper Windows binary and put `piper` on `PATH`, or set:

```powershell
$env:JARVIS_PIPER_EXE = "C:\path\to\piper.exe"
$env:JARVIS_PIPER_MODEL = "$env:USERPROFILE\Downloads\en_GB-northern_english_male-medium.onnx"
```

Without Piper, replies still print in the terminal (`[jarvis speak] …` fallback).

## Run the headless loop

Interactive REPL (real Claude brain):

```powershell
py -3.13 -m jarvis
```

One-shot:

```powershell
py -3.13 -m jarvis --once "open notepad"
py -3.13 -m jarvis --no-speak --once "how much free disk space do I have?"
```

In-process fake brain (no network, for demos/tests):

```powershell
py -3.13 -m jarvis --fake --no-speak --once "open notepad"
```

REPL commands: type a request, `:n` new session, `:q` quit.

### Environment

| Variable | Meaning |
|----------|---------|
| `JARVIS_MODEL` | Claude model (default `sonnet`) |
| `JARVIS_SPEAK` | `0` to disable Piper |
| `JARVIS_PIPER_EXE` | Path to `piper` binary |
| `JARVIS_PIPER_MODEL` | Path to `.onnx` voice |

## Architecture (issue 02)

```
handle_command(transcript_text) → CommandResult(reply, actions)
        │
        ▼
   Brain.ask(text)     ← FakeBrain | ClaudeCodeBrain (provider adapter)
        │
        ▼
   Speaker.speak(reply) ← FakeSpeaker | PiperSpeaker
```

- **Tiered autonomy:** safe tools auto-run via Claude `--allowedTools` +
  `--permission-mode acceptEdits`, with approved folders passed as `--add-dir`.
  Risky tools are omitted from the allow-list (denied, not prompted). The system
  prompt forbids destructive shell and out-of-folder writes; deeper Bash
  path-scoping is future hardening. Secrets are refused in the system prompt
  and fake rules.
- **Persistence:** `ClaudeCodeBrain` keeps a `session_id` and passes `--resume`.
- **Automated seam:** inject `FakeBrain` + `FakeSpeaker`; assert on reply + actions.

## Tests

```powershell
py -3.13 -m pytest tests -m "not smoke" -v
```

Optional real-CLI smoke (uses your Claude subscription):

```powershell
py -3.13 -m pytest tests/test_smoke_claude.py -m smoke -v
```

## Docs

- [PRD](./PRD-jarvis-v1.md)
- [Design / shared understanding](./JARVIS-V1-DESIGN.md)
- Local issue board: `.scratch/jarvis-v1/`
