"""Record from the default microphone until silence (or limits)."""

from __future__ import annotations

import queue
import time
from dataclasses import dataclass

import numpy as np

from jarvis.audio.silence import SilenceConfig, SilenceTracker


@dataclass(frozen=True)
class RecordResult:
    """Captured mono float32 audio at the configured sample rate."""

    audio: np.ndarray
    sample_rate: int
    duration_s: float
    heard_speech: bool


class MicRecorder:
    """Capture until SilenceTracker says done.

    Production path opens a sounddevice InputStream. Tests inject pre-built
    blocks via ``blocks`` (one shot) or ``block_sessions`` (one list per
    ``record_until_silence`` call — needed for front-door multi-cycle tests).
    """

    def __init__(
        self,
        *,
        config: SilenceConfig | None = None,
        block_ms: int = 50,
        blocks: list[np.ndarray] | None = None,
        block_sessions: list[list[np.ndarray]] | None = None,
    ) -> None:
        self.config = config or SilenceConfig()
        self.block_ms = block_ms
        if block_sessions is not None:
            self._sessions: list[list[np.ndarray]] | None = list(block_sessions)
        elif blocks is not None:
            self._sessions = [blocks]
        else:
            self._sessions = None
        self._session_i = 0

    def record_until_silence(self) -> RecordResult:
        if self._sessions is not None:
            if self._session_i >= len(self._sessions):
                # No more scripted audio — behave like a quiet timeout.
                return RecordResult(
                    audio=np.zeros(0, dtype=np.float32),
                    sample_rate=self.config.sample_rate,
                    duration_s=0.0,
                    heard_speech=False,
                )
            blocks = self._sessions[self._session_i]
            self._session_i += 1
            return self._record_from_blocks(blocks)
        return self._record_from_mic()

    def _record_from_blocks(self, blocks: list[np.ndarray]) -> RecordResult:
        tracker = SilenceTracker(self.config)
        frames: list[np.ndarray] = []
        for block in blocks:
            flat = np.asarray(block, dtype=np.float32).reshape(-1)
            frames.append(flat)
            tracker.feed(flat)
            if tracker.done:
                break
        return self._pack(frames, tracker)

    def _record_from_mic(self) -> RecordResult:
        try:
            import sounddevice as sd
        except ImportError as e:
            raise RuntimeError(
                "sounddevice is required for mic capture. "
                'Install with: py -3.13 -m pip install -e ".[voice]"'
            ) from e

        cfg = self.config
        sr = cfg.sample_rate
        blocksize = max(1, int(sr * self.block_ms / 1000))
        q: queue.Queue[np.ndarray] = queue.Queue()

        def callback(indata, frames, time_info, status) -> None:  # noqa: ARG001
            q.put(indata.copy())

        tracker = SilenceTracker(cfg)
        frames: list[np.ndarray] = []
        stream = sd.InputStream(
            samplerate=sr,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            callback=callback,
        )
        stream.start()
        try:
            # Poll until silence ends or hard limits fire inside the tracker.
            deadline = time.monotonic() + cfg.max_record_s + cfg.max_lead_silence_s + 2.0
            while not tracker.done and time.monotonic() < deadline:
                try:
                    block = q.get(timeout=0.2)
                except queue.Empty:
                    continue
                flat = np.asarray(block, dtype=np.float32).reshape(-1)
                frames.append(flat)
                tracker.feed(flat)
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

        return self._pack(frames, tracker)

    def _pack(self, frames: list[np.ndarray], tracker: SilenceTracker) -> RecordResult:
        if frames:
            audio = np.concatenate(frames).astype(np.float32, copy=False)
        else:
            audio = np.zeros(0, dtype=np.float32)
        sr = self.config.sample_rate
        return RecordResult(
            audio=audio,
            sample_rate=sr,
            duration_s=float(audio.size) / sr if audio.size else 0.0,
            heard_speech=tracker.heard_speech,
        )
