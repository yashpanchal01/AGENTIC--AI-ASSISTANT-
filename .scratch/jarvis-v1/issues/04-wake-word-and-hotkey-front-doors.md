# 04 — Wake word + hotkey as the only front doors

Status: done

## What to build

Wire the chosen wake-word detector and a push-to-talk hotkey as the only ways into the voice pipeline. Support one-breath ("Jarvis, …") and two-step (say "Jarvis", acknowledge, then speak). Wake word required every command — no open-mic follow-up window. Hotkey path must use the exact same pipeline as wake word (record → whisper → brain → Piper).

## Acceptance criteria

- [x] Saying the wake word starts arming/listening and runs a full command path
- [x] One-breath and two-step utterance styles both work
- [x] Every new command requires the wake word again (no open-mic follow-up window)
- [x] Configurable hotkey push-to-talk triggers the same pipeline end-to-end
- [x] Wake-word detection remains fully local

## Blocked by

- 01 — Wake-word A/B bench
- 03 — Mic → silence end → whisper into the loop

## User stories covered

1–4, 6–7

## Comments

Implemented under `jarvis/wake/`:
- Detectors: Porcupine (prefer when `PICOVOICE_ACCESS_KEY` set) + openWakeWord fallback; `FakeWakeDetector` for tests
- Shared entry: `run_armed_pipeline` used by both wake and hotkey
- `FrontDoorSession` continuous loop; CLI `--daemon` / `--front-door`
- Phrase strip for one-breath; two-step acknowledge ("Yes?") when wake-only
- Optional `pynput` hotkey (default `ctrl+shift+j`); disable with `--no-hotkey`
- Tests: `tests/test_wake_front_door.py`, `tests/test_cli_daemon.py`
