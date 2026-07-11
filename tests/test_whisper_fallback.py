"""WhisperTranscriber retries on CPU when GPU encode fails mid-transcribe."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from jarvis.stt.whisper import WhisperTranscriber


class _OkCpuModel:
    def transcribe(self, audio, **kwargs):  # noqa: ANN001, ARG002
        seg = SimpleNamespace(text=" open notepad ")
        return iter([seg]), None


def test_transcribe_retries_on_cpu_after_gpu_encode_error() -> None:
    class _FailingGpu:
        def transcribe(self, audio, **kwargs):  # noqa: ANN001, ARG002
            raise RuntimeError(
                "Library cublas64_12.dll is not found or cannot be loaded"
            )

    loads: list[str] = []

    def fake_whisper_model(name, device="cpu", compute_type="int8"):  # noqa: ANN001
        loads.append(f"{device}:{name}")
        if device == "cuda":
            return _FailingGpu()
        return _OkCpuModel()

    stt = WhisperTranscriber(device="cuda", compute_type="int8_float16")
    stt._WhisperModel = fake_whisper_model  # type: ignore[method-assign]

    audio = np.full(16_000, 0.05, dtype=np.float32)
    text = stt.transcribe(audio, sample_rate=16_000)

    assert text == "open notepad"
    assert stt.using_cpu_fallback is True
    assert any(x.startswith("cuda:") for x in loads)
    assert any(x.startswith("cpu:") for x in loads)
