# 01 — Wake-word A/B bench (openWakeWord vs Porcupine)

Status: done-provisional (full dual-engine mic trials pending Picovoice key)

## What to build

A standalone mic bench (not wired into the app) that compares openWakeWord and Porcupine for detecting "Jarvis" on this machine's actual microphone. Measure detection quality and latency; record false positives/negatives under normal room noise. Produce a written pick (and why) so later issues can wire the winner only.

Hard constraints: Windows 11; local-only detection (no audio leaves the PC); Porcupine ships a prebuilt "jarvis" keyword but needs a free Picovoice key; Windows SAPI and browser speech are already rejected.

## Acceptance criteria

- [x] Bench script runs on this PC and exercises detectors against the real mic (`benches/wake_word_ab/run_bench.py`; openWakeWord smoke + idle FP listen verified)
- [x] Results schema includes latency and FP/FN notes; smoke results + provisional rationale in `benches/wake_word_ab/DECISION.md` (full dual-engine latency/FN after `PICOVOICE_ACCESS_KEY` + interactive trials)
- [x] One detector chosen with written rationale: **Porcupine** provisional (product phrase `jarvis`); openWakeWord is the verified no-key fallback
- [x] No production app wiring required for this issue

## Blocked by

None - can start immediately

## User stories covered

3, 4 (decision path for wake-word detector)

## Comments
