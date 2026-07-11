# VRAM coexistence bench (issue #9)

JARVIS shares a 6 GB GPU (RTX 4050) with games and other CUDA apps. The
known fallback is **unloading the faster-whisper model between commands** so
VRAM is free when idle.

## What this exercises

1. Load `WhisperTranscriber` (GPU if available).
2. Transcribe a short synthetic clip.
3. Call `unload()` and report whether the model was dropped.
4. Optionally re-transcribe (reload) to prove the loop still works.

This is a **manual / semi-manual** bench — GPU memory numbers depend on
drivers, torch, and whatever else is using the card. Automated unit tests
cover the unload *contract* via `FakeTranscriber.unload_calls`.

## Run

```powershell
# From repo root; needs voice extra for real whisper
py -3.13 -m pip install -e ".[voice]"
py -3.13 benches/vram_coexist/run_bench.py

# Force unload path in the live app (between commands):
$env:JARVIS_UNLOAD_STT = "1"
py -3.13 -m jarvis --listen
```

## Manual coexistence check

1. Start a GPU-heavy app (game, Blender, etc.).
2. With `JARVIS_UNLOAD_STT=1`, run one voice command — it should still
   transcribe (reload cost is acceptable butler latency).
3. Between commands, GPU memory used by whisper should drop (Task Manager
   / `nvidia-smi` if available).
4. Without unload, if CUDA OOM appears, enable unload — that is the
   designed fallback.

## Expected outcome

- Unload returns the process to a state where `is_loaded` is false.
- Next `transcribe` reloads without user action.
- Offline honesty is independent: wake + STT + Piper work with Wi-Fi off;
  only the brain needs the network (`JARVIS_CHECK_NET`, default on).
