# 03 — Mic → silence end → whisper (+ hotwords) into the same loop

Status: done

## What to build

Replace typed input with voice for the headless core loop: capture from the mic after a trigger, stop on silence, transcribe locally with faster-whisper on GPU, apply a tunable hotwords/dictionary list for proper nouns, and feed **raw** transcript text into the existing `handle_command` path (no polish model). Output remains Piper as already established by the core loop.

Copy proven mic/whisper/dictionary patterns from LocalFlow; do not modify LocalFlow. Stay within VRAM budget (RTX 4050 6 GB); no Ollama.

## Acceptance criteria

- [x] User can speak a command and the same brain path acts and replies via Piper (`py -3.13 -m jarvis --listen`; REPL `:listen`)
- [x] Recording ends on silence without a second keypress or wake word (that entry is a later issue) — `SilenceTracker` ~0.8 s trailing quiet
- [x] Hotwords/dictionary can be tuned so common proper nouns improve over baseline (`dictionary.txt` + `fix_terms`)
- [x] Raw whisper text goes to the brain with no intermediate polish model (`listen_and_handle` → `handle_command`)
- [x] Works under the machine constraints (`py -3.13`, shared 6 GB VRAM) — `distil-large-v3.5-ct2` + `int8_float16`, CPU fallback

## Blocked by

- 02 — Headless core loop

## User stories covered

5, 8

## Comments

Implemented modules: `jarvis/audio/` (silence + mic capture), `jarvis/stt/` (whisper + dictionary), `jarvis/voice.py` (listen → handle_command). Automated tests cover silence, dictionary, voice wiring with fakes, and CLI `--fake-stt`. Wake word / hotkey front doors are issue 04.
