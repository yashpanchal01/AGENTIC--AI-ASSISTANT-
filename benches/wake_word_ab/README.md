# Wake-word A/B bench (issue 01)

Standalone microphone bench comparing **openWakeWord** (`hey jarvis`) and
**Porcupine** (built-in `jarvis`) on this PC. Not wired into the app.

## Why

The PRD requires a local wake word before every command. Detector choice
(openWakeWord vs Porcupine) was left open until measured on the real mic.

## Setup

```text
py -3.13 -m pip install -r benches/wake_word_ab/requirements.txt
```

Porcupine needs a free Picovoice access key:

1. Create a key at https://console.picovoice.ai/
2. In PowerShell for the session:

```text
$env:PICOVOICE_ACCESS_KEY = "your_key_here"
```

openWakeWord needs no key; models download on first load.

## Run

Full interactive bench (≈60s idle + 8 trials per detector):

```text
py -3.13 benches/wake_word_ab/run_bench.py
```

Smoke (short):

```text
py -3.13 benches/wake_word_ab/run_bench.py --fp-seconds 15 --trials 3
```

List mic devices:

```text
py -3.13 benches/wake_word_ab/run_bench.py --list-devices
```

## Outputs

| File | Purpose |
|------|---------|
| `DECISION.md` | Written pick + latency / FP / FN notes |
| `results/latest.json` | Machine-readable summary |

## Unit tests (metrics only)

Audio is manual; pure scoring logic is unit-tested:

```text
py -3.13 -m unittest benches.wake_word_ab.tests.test_metrics -v
```

Or:

```text
py -3.13 benches/wake_word_ab/tests/test_metrics.py -v
```

## Constraints

- Windows 11, local-only detection (no cloud STT / browser speech)
- Python: `py -3.13`
- Windows SAPI and browser speech are already rejected by the PRD
