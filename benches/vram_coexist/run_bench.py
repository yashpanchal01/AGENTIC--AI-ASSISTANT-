"""Exercise Whisper load → transcribe → unload (VRAM coexistence fallback).

Usage:
  py -3.13 benches/vram_coexist/run_bench.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Repo root on path when run as a script.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _synthetic_audio(seconds: float = 1.0, sr: int = 16_000):
    import numpy as np

    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    # Quiet tone so VAD still has energy.
    return (0.05 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def main() -> int:
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        print("numpy required — install with: py -3.13 -m pip install -e \".[voice]\"")
        return 2

    try:
        from jarvis.stt.whisper import WhisperTranscriber
    except Exception as e:  # noqa: BLE001
        print(f"Cannot import WhisperTranscriber: {e}")
        return 2

    print("=== VRAM coexistence bench (issue #9) ===")
    audio = _synthetic_audio()
    stt = WhisperTranscriber(device="cuda", compute_type="int8_float16")

    t0 = time.perf_counter()
    try:
        text1 = stt.transcribe(audio, sample_rate=16_000)
    except Exception as e:  # noqa: BLE001
        print(f"transcribe failed: {e}")
        return 1
    load_s = time.perf_counter() - t0
    print(f"loaded+transcribe: {load_s:.2f}s  text={text1!r}  loaded={stt.is_loaded}")

    t1 = time.perf_counter()
    stt.unload()
    unload_s = time.perf_counter() - t1
    print(f"unload: {unload_s:.3f}s  loaded={stt.is_loaded}")

    t2 = time.perf_counter()
    text2 = stt.transcribe(audio, sample_rate=16_000)
    reload_s = time.perf_counter() - t2
    print(f"reload+transcribe: {reload_s:.2f}s  text={text2!r}  loaded={stt.is_loaded}")

    stt.unload()
    print("final unload ok; set JARVIS_UNLOAD_STT=1 to use this in the live app")
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
