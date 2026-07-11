# JARVIS v1 — Shared Understanding (2026-07-11)

The agreed design for a Windows-first, voice-driven AI assistant. This document
is the output of the full grilling session; a build session should start from
here without re-litigating these decisions.

## Vision (one line)

Say "Jarvis, …" from anywhere on the PC → it acts (files, apps, terminal,
email, music) with zero permission clicking for safe actions → answers back in
a natural voice, through a slick native overlay.

## The pipeline

```
"Jarvis…" (wake word, local)
  → record until silence
  → faster-whisper (speech → text, local GPU)
  → Claude Code headless (text → decisions → actions, cloud brain)
  → Piper (reply text → speech, local)
  → Aurora-style overlay shows state throughout
```

## Locked decisions

| # | Decision | Choice | Why |
|---|----------|--------|-----|
| 1 | Permission policy | **Tiered autonomy** | Auto-run read-only + reversible actions in approved folders; ask before destructive/outward/system-level; secrets never. Maps directly to Claude's `--allowedTools` config — verified zero-prompt in prototype. |
| 2 | Brain | **Claude Code headless** behind a provider-swappable adapter | Free on existing subscription, frontier reasoning, does real tool-work natively. Grok/others = config swap later. |
| 3 | Input | **Wake word required every time** ("Jarvis") | Both styles: one-breath ("Jarvis, open notepad") and two-step (say "Jarvis", wait for beep, then speak). No open-mic follow-up window (user decision: predictability > convenience). Hotkey push-to-talk as fallback. Detector: openWakeWord or Porcupine (prebuilt "jarvis" keyword) — NOT Windows SAPI (broken on this machine) and NOT browser speech (Brave blocks it; was prototype-only). |
| 4 | Integrations v1 | **Gmail read-only + Spotify** (+ Calendar free via same Google OAuth) | Files/apps/terminal/web come free with the brain. Messaging/sending = explicitly not v1 (outward-facing risk). |
| 5 | App tech | **Python + PySide6 native overlay** — separate project, LocalFlow untouched | Copy LocalFlow's proven parts (mic capture, faster-whisper setup + dictionary, Aurora overlay painting). No web/browser/Electron — user veto. QML is the upgrade path if animations feel stiff. |
| 6 | Voice out | **Piper** (user already downloaded a ~60 MB voice and likes it) | Local, instant, free. Kokoro (~1 GB RAM, better) or ElevenLabs (paid, best) are one-function swaps later. |
| 7 | Memory | **Markdown notes + retrieval** (from prior session) | Dated/stable notes, tags, summaries; human-editable; no credentials in markdown. Within a conversation, Claude session resume covers short-term context. |
| 8 | No polish model | Raw whisper text goes straight to Claude | Commands are intent, not dictation; Claude decodes messy transcripts fine. Skipping Ollama frees VRAM. |

## Prototype findings (validated 2026-07-11, `jarvis-proto/`)

- **Zero-prompt operation works:** `--allowedTools` + permission-mode flags ran
  real file/app actions with no clicking. Tiered policy = pure configuration.
- **Latency (sonnet):** ~7 s simple command, ~15–20 s multi-step (it batches
  steps into one script — step count barely multiplies cost). Cold start adds
  ~10–12 s to the *first* command only.
- **Architecture consequence:** v1 must keep **one persistent agent
  process/conversation** (Claude Agent SDK or session-resume), never spawn
  per-command. Prototype's `--resume` approach proved context carry-over
  (corrections like "actually, close it" work).
- **Sandbox:** headless Claude's sandbox blocks GUI app launches; v1 config
  must allow app-launch in the safe tier (validated with bypass + retry).
- **Browser speech was prototype-only:** works in Chrome, blocked in Brave,
  online service — replaced by local whisper + wake word in v1.

## Hard constraints (user's machine)

- Windows 11, RTX 4050 **6 GB VRAM**, **8 GB RAM** — whisper shares the GPU;
  no Ollama needed for JARVIS (frees VRAM vs LocalFlow).
- Python via **`py -3.13`** (not bare `python`).
- LocalFlow repo is sacred: copy from it, never modify it.
- Cost ceiling: $0 beyond existing Claude subscription.

## V1 scope

**In:** wake word → whisper → Claude (persistent session, tiered permissions)
→ act → Piper reply; Aurora-style overlay (canonical state names:
**armed / heard / working / speaking**); Gmail read-only + Calendar + Spotify;
markdown memory; starts with Windows; tray icon; settings file; audit log.

**Out (explicitly):** sending email/messages, browser-tab UI, Ollama polish,
hybrid local model, always-listening ambient mode, phone app, ElevenLabs.

## Known risks / open items for the build

1. **Wake-word detector quality** — openWakeWord vs Porcupine ("jarvis"
   built-in, needs free Picovoice key) not yet bench-tested on this mic.
   First build task: A/B it standalone before wiring anything.
2. **Whisper accuracy on proper nouns** — LocalFlow observed "Claude Code" →
   "broadcourt" etc. Less critical for intent commands, but reuse the
   dictionary/hotwords tuning; consider distil-large-v3.5 upgrade later.
3. **VRAM pressure** — whisper permanently resident + games/other GPU use may
   conflict; measure, consider unloading model between commands if needed.
4. **Claude usage limits** — heavy JARVIS use shares the subscription budget.
5. **Latency honesty** — 7–20 s per command is a capable butler, not movie
   banter. Persistent session narrows it; do not promise sub-second.

## Suggested build order

1. Wake-word detector A/B test (standalone script, mic → detection latency).
2. Core loop headless: wake → record → whisper → Claude (persistent, tiered
   flags) → Piper. No UI — prove the loop in a terminal.
3. Overlay: JARVIS variant of Aurora Mono via LocalFlow's prototype harness
   (screenshot-iterate before wiring).
4. Integrations: Google OAuth (Gmail read-only + Calendar), then Spotify.
5. Polish: autostart with Windows, tray icon, settings file, audit log.

Each step is independently testable; stop-anywhere shippable.

## Artifacts

- `jarvis-proto/` — throwaway prototype (brain validation + browser voice
  demo). `NOTES.md` holds the verdict. Delete once v1's core loop runs.
- `C:\tmp\jarvis-handoff.md` — prior session's handoff (superseded by this doc).
- LocalFlow reference: `C:\Users\YASH PANCHAL\localflow` — mic/whisper/overlay
  code to copy; `docs/localflow-handoff-2026-07-09.md` documents its state.
