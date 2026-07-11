# JARVIS v1

Windows-first, voice-driven AI assistant. This repo ships the **headless core
loop**, **mic → silence → whisper**, **wake word + hotkey front doors**, and the
**Aurora overlay** (armed → heard → working → speaking).

## Requirements

- Windows 11
- Python **3.13** via `py -3.13`
- **Grok CLI** on `PATH` (default brain — SuperGrok / `~/.grok/bin/grok`)  
  or [Claude Code](https://claude.ai/code) CLI if you switch with `--brain claude`
- Optional: [Piper](https://github.com/rhasspy/piper) binary + ONNX voice for spoken replies
- Optional voice path: GPU (RTX 4050 6 GB) + `pip install -e ".[voice]"`
- Optional wake/hotkey: `pip install -e ".[wake]"` (+ free `PICOVOICE_ACCESS_KEY` for Porcupine)
- Optional UI: `pip install -e ".[ui]"` (PySide6 Aurora overlay)
- Optional Google (Gmail + Calendar read-only): `pip install -e ".[google]"`

## Setup

```powershell
cd NEW_project
py -3.13 -m pip install -e ".[dev]"
# Voice (mic + faster-whisper):
py -3.13 -m pip install -e ".[voice]"
# Wake word + global hotkey:
py -3.13 -m pip install -e ".[wake]"
# Aurora overlay:
py -3.13 -m pip install -e ".[ui]"
# Gmail + Calendar (read-only OAuth):
py -3.13 -m pip install -e ".[google]"
# Everything:
py -3.13 -m pip install -e ".[all]"
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

## Run

Interactive REPL (**default brain: Grok CLI**, typed input):

```powershell
py -3.13 -m jarvis
# Force Grok / Claude / fake:
py -3.13 -m jarvis --brain grok
py -3.13 -m jarvis --brain claude
py -3.13 -m jarvis --brain fake
```

One-shot typed command:

```powershell
py -3.13 -m jarvis --once "open notepad"
py -3.13 -m jarvis --no-speak --once "how much free disk space do I have?"
# Pin model (Grok):
py -3.13 -m jarvis --model grok-build --once "open notepad"
```

Env switches: `JARVIS_BRAIN=grok|claude|fake`, `JARVIS_GROK_BIN`, `JARVIS_GROK_MODEL`.

**One-shot voice** (mic → silence → whisper → brain → Piper, no wake word):

```powershell
py -3.13 -m jarvis --listen
py -3.13 -m jarvis --fake --no-speak --listen
```

**Front door daemon** (local wake word + hotkey; wake required every command):

```powershell
# Real detectors (Porcupine if PICOVOICE_ACCESS_KEY set, else openWakeWord)
# Note: openWakeWord may download ONNX models on first run (needs internet once;
# after that detection is fully offline). Prefer Porcupine for offline-first boot.
py -3.13 -m jarvis --daemon
py -3.13 -m jarvis --front-door --hotkey ctrl+shift+j

# Fake brain / no Piper / no global hotkey (dev)
py -3.13 -m jarvis --fake --no-speak --no-hotkey --daemon

# Automated demo (fake wake + fake STT, one cycle)
py -3.13 -m jarvis --fake --no-speak --no-hotkey --fake-wake --fake-stt "open notepad" --daemon --max-cycles 1 --no-overlay
```

### Live-in polish (autostart, tray, settings, audit)

JARVIS can run as a resident: starts with Windows, system tray Pause/Resume/Quit,
user settings file, and an append-only audit log.

```powershell
# Register --daemon to start with Windows (HKCU Run key "JARVIS")
py -3.13 -m jarvis --install-autostart
# Reboot demo: restart PC, then speak a command — nothing to launch by hand.
py -3.13 -m jarvis --uninstall-autostart

# Daemon with tray (default when PySide6 is installed) + Aurora overlay
py -3.13 -m jarvis --daemon
# Pause from the tray makes wake word + hotkey do nothing until Resume; Quit stops fully.
```

**Settings** (`%USERPROFILE%\.jarvis\settings.json`, or `JARVIS_SETTINGS` / `--settings`):

```json
{
  "hotkey": "ctrl+shift+j",
  "approved_folders": ["C:\\Users\\You\\Documents", "C:\\Users\\You\\Downloads"],
  "voice": "C:\\Users\\You\\Downloads\\en_GB-northern_english_male-medium.onnx"
}
```

Edit the file and restart the daemon (or reboot if autostart is on) — no code changes.

**Audit log** (`%USERPROFILE%\.jarvis\audit.log`): JSON-lines with timestamps for
wake/hotkey arm, transcripts, command results, pause/resume/quit, autostart.
Disable for a run with `--no-audit`.

Wake styles:

- **One-breath:** “Jarvis, open notepad” — command rides in the same utterance; leading wake phrase is stripped from the transcript.
- **Two-step:** say “Jarvis” alone → brief “Yes?” → speak the command.
- After each command JARVIS returns to wake listening (no open-mic follow-up).
- **Hotkey** (default `ctrl+shift+j`) runs the **same** `run_armed_pipeline` as wake.

In the REPL, type `:listen` (or `:v`) for one voice capture without wake.

Inject a transcript without the mic (tests / demos):

```powershell
py -3.13 -m jarvis --fake --no-speak --fake-stt "open notepad"
```

### Google OAuth — Gmail + Calendar (read-only)

One-time sign-in covers **both** Gmail and Calendar. Scopes are strictly
read-only (`gmail.readonly` + `calendar.readonly`). Send / reply / forward /
create-event are refused aloud. Tokens live under `%LOCALAPPDATA%\Jarvis\`
(never under human-readable memory notes).

```powershell
# 1) Place a Desktop OAuth client JSON from Google Cloud Console, then:
$env:JARVIS_GOOGLE_CLIENT_SECRETS = "$env:LOCALAPPDATA\Jarvis\google_client_secrets.json"
py -3.13 -m pip install -e ".[google]"
py -3.13 -m jarvis --google-login

# 2) Voice / text demos (sample data, no OAuth):
py -3.13 -m jarvis --fake --no-speak --once "any new email?"
py -3.13 -m jarvis --fake --no-speak --once "what's on my calendar today?"
py -3.13 -m jarvis --fake --no-speak --once "am I free at three?"
py -3.13 -m jarvis --fake --no-speak --once "send an email to bob"   # declined

# Real signed-in account:
py -3.13 -m jarvis --no-speak --once "any new email?"
```

### Aurora overlay

Native PySide6 pill (not Electron/web). States: **armed → heard → working → speaking** (+ rest hides). Does not steal keyboard focus.

```powershell
# With one-shot voice or daemon (daemon enables overlay by default when PySide6 is installed)
py -3.13 -m jarvis --overlay --listen
py -3.13 -m jarvis --daemon

# Screenshot harness → PNGs for visual review
py -3.13 -m jarvis --shoot-overlay
py -3.13 -m jarvis.overlay --shoot
# default out: benches/overlay_shots/results/aurora-*.png

# Live state demo
py -3.13 -m jarvis --demo-overlay
```

### Environment

| Variable | Meaning |
|----------|---------|
| `JARVIS_MODEL` | Claude model (default `sonnet`) |
| `JARVIS_SPEAK` | `0` to disable Piper |
| `JARVIS_PIPER_EXE` | Path to `piper` binary |
| `JARVIS_PIPER_MODEL` | Path to `.onnx` voice |
| `JARVIS_WHISPER_MODEL` | faster-whisper model (default distil-large-v3.5-ct2) |
| `JARVIS_WHISPER_DEVICE` | `cuda` (default) or `cpu` |
| `JARVIS_WHISPER_COMPUTE` | default `int8_float16` (fits 6 GB VRAM) |
| `JARVIS_DICTIONARY` | Path to hotwords file (default `./dictionary.txt`) |
| `JARVIS_CHECK_NET` | `0` to skip offline pre-check before the cloud brain (default on) |
| `JARVIS_UNLOAD_STT` | `1` to free Whisper VRAM between commands (GPU coexistence) |
| `JARVIS_HOTKEY` | Push-to-talk combo (default `ctrl+shift+j`) |
| `JARVIS_HOTKEY_ENABLE` | `0` to disable hotkey |
| `JARVIS_WAKE_THRESHOLD` | openWakeWord threshold (default `0.5`) |
| `JARVIS_WAKE_SENSITIVITY` | Porcupine sensitivity (default `0.5`) |
| `PICOVOICE_ACCESS_KEY` | Free Picovoice key → prefer Porcupine (`jarvis`) |
| `JARVIS_GOOGLE_CLIENT_SECRETS` | Path to Google OAuth Desktop client JSON |
| `JARVIS_GOOGLE_TOKEN` | Override path for stored OAuth tokens |
| `JARVIS_MEMORY_DIR` | Markdown memory root (tokens are *never* stored here) |
| `JARVIS_HOME` | Root for settings + audit log (default `%USERPROFILE%\.jarvis`) |
| `JARVIS_SETTINGS` | Override path to `settings.json` |

### Graceful degradation (GitHub #9)

- Failures are **spoken in plain language** (never silent, never a stack trace).
- Offline: a short TCP check runs before the cloud brain. If the network is
  down, wake word / STT / Piper still work and JARVIS says its brain is
  unreachable (`JARVIS_CHECK_NET=0` skips the pre-check).
- VRAM: set `JARVIS_UNLOAD_STT=1` to free the Whisper model between commands so
  games can share the 6 GB GPU. Bench notes: `benches/vram_coexist/`.

### Hotwords / dictionary

Edit `dictionary.txt` at the project root (one term per line). Whisper is biased
toward these via `hotwords` + `initial_prompt`. Narrow post-fixes for known
mishears (`broadcourt` → `Claude Code`, etc.) apply after STT. **No polish
model** — raw text goes straight to the brain.

## Architecture

```
[wake word | hotkey]     ← only front doors in --daemon mode
        │
        ▼
  run_armed_pipeline()   ← shared by wake + hotkey
        │
        ▼
  MicRecorder.record_until_silence()
        │
        ▼
  Transcriber.transcribe(audio)   (+ strip leading wake phrase if source=wake)
        │  two-step if wake-only transcript → acknowledge → record again
        ▼
  handle_command(text) → CommandResult(reply, actions)
        │
        ▼
   Brain.ask / Speaker.speak
        │
        ▼
   Overlay: armed → heard → working → speaking → rest
```

- **Wake detectors (local only):** Porcupine built-in `jarvis` when
  `PICOVOICE_ACCESS_KEY` is set; otherwise openWakeWord `hey jarvis`.
  See `benches/wake_word_ab/DECISION.md`.
- **Tiered autonomy:** safe tools auto-run via Claude `--allowedTools` +
  `--permission-mode acceptEdits`. Destructive / system / outward commands hit
  an ask-first gate (voice yes/no + overlay Yes/No); secrets stay hard-denied.
  Post-confirm execution is foreground in v1 (no second long-task "On it." race).
- **Automated seam:** `FakeBrain` + `FakeSpeaker` + `FakeTranscriber` +
  `FakeWakeDetector` + `FakeOverlay`. No real mic in CI.

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
- Wake A/B decision: `benches/wake_word_ab/DECISION.md`
