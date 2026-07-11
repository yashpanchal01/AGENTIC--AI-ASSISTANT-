# Wake-word detector decision (issue 01)

Generated: 2026-07-11 (bench tooling + smoke validation)

Standalone A/B bench on this machine's real microphone. Local-only detection —
no audio leaves the PC.

## Recommendation

**Provisional winner for wiring: Porcupine** (built-in `jarvis`).

**Working fallback today: openWakeWord** (`hey jarvis`) — verified loadable and
idle-clean on this PC's default mic without any cloud key.

### Why Porcupine is the intended pick

| Factor | Porcupine | openWakeWord |
|--------|-----------|--------------|
| Product phrase | **`jarvis`** (matches PRD one-breath / two-step UX) | **`hey jarvis`** only in bundled models |
| Access | Free Picovoice key required | Fully free / open |
| On this PC (2026-07-11) | Not measured — `PICOVOICE_ACCESS_KEY` unset | Loaded OK; 0 false positives in 10 s idle listen |
| Runtime | Lightweight commercial engine | ONNX; slightly heavier multi-model stack |

The PRD wake contract is **"Jarvis"** (not "Hey Jarvis"). Using openWakeWord's
bundled model would force a product phrasing change or a custom-trained model.
Porcupine already ships the right keyword. Cost remains $0 with the free
developer key the design doc already anticipated.

### Re-validation required before issue 04 wires the front door

Run the full interactive A/B once the Picovoice key is set. If Porcupine's hit
rate or false-positive rate is clearly worse than openWakeWord on this mic,
**override this provisional pick** and update this file with the measured
numbers.

```text
$env:PICOVOICE_ACCESS_KEY = "your_key_here"
py -3.13 benches/wake_word_ab/run_bench.py --fp-seconds 60 --trials 8
```

That command overwrites `DECISION.md` and `results/latest.json` with measured
latency, hit rate, and FP/hour for both engines.

## Smoke results (this session)

### openWakeWord

- **Phrase:** `hey jarvis`
- **Status:** available
- **False positives:** 0 in 10 s idle listen (device: system default —
  Microphone Array Realtek)
- **True-positive trials:** not run in this non-interactive smoke (requires a
  speaker at the mic)
- **Notes:** `hey_jarvis` model keys resolved; silent-frame process returns no
  detection (healthy)

### Porcupine

- **Phrase:** `jarvis`
- **Status:** unavailable — `PICOVOICE_ACCESS_KEY` not set
- **Action:** create a free key at https://console.picovoice.ai/ and re-run

## Product notes

- openWakeWord's bundled model is **"hey jarvis"** (two words).
- Porcupine ships a prebuilt **"jarvis"** keyword (matches PRD phrasing).
- Porcupine needs a free Picovoice access key (`PICOVOICE_ACCESS_KEY`).
- Windows SAPI and browser speech are already rejected (see PRD).

## How to re-run

```text
py -3.13 -m pip install -r benches/wake_word_ab/requirements.txt
$env:PICOVOICE_ACCESS_KEY = "your_key_here"
py -3.13 benches/wake_word_ab/run_bench.py
```

Smoke (short):

```text
py -3.13 benches/wake_word_ab/run_bench.py --fp-seconds 15 --trials 3
```

Unit tests (metrics only, no mic):

```text
py -3.13 benches/wake_word_ab/tests/test_metrics.py -v
```
