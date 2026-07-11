"""Stream mic (or injected frames) into a wake detector until a hit."""

from __future__ import annotations

import queue
import threading
import time
from typing import Iterator, Literal

import numpy as np

from jarvis.wake.base import SAMPLE_RATE, Detection, WakeDetector

TriggerSource = Literal["wake", "hotkey"]


def float_to_int16(block: np.ndarray) -> np.ndarray:
    flat = np.asarray(block, dtype=np.float32).reshape(-1)
    clipped = np.clip(flat, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


def iter_int16_frames(
    samples_i16: np.ndarray,
    frame_length: int,
) -> Iterator[np.ndarray]:
    """Yield fixed-size int16 frames from a contiguous buffer (drop short tail)."""
    n = int(samples_i16.size)
    i = 0
    while i + frame_length <= n:
        yield samples_i16[i : i + frame_length]
        i += frame_length


def wait_for_wake(
    detector: WakeDetector,
    *,
    frames: Iterator[np.ndarray] | None = None,
    hotkey_event: threading.Event | None = None,
    stop_event: threading.Event | None = None,
    poll_s: float = 0.02,
    sample_rate: int = SAMPLE_RATE,
) -> tuple[TriggerSource, Detection | None]:
    """Block until wake detection, hotkey, or stop.

    Returns:
      ("wake", Detection) on wake word
      ("hotkey", None) on hotkey
      raises InterruptedError if stop_event is set first

    When *frames* is provided, frames are int16 arrays of any length (buffered
    into detector.frame_length chunks). When *frames* is None, opens the real
    default microphone via sounddevice.
    """
    if frames is not None:
        return _wait_from_frames(
            detector,
            frames=frames,
            hotkey_event=hotkey_event,
            stop_event=stop_event,
            poll_s=poll_s,
        )
    return _wait_from_mic(
        detector,
        hotkey_event=hotkey_event,
        stop_event=stop_event,
        sample_rate=sample_rate,
    )


def _drain_hotkey_or_stop(
    hotkey_event: threading.Event | None,
    stop_event: threading.Event | None,
) -> TriggerSource | None:
    if stop_event is not None and stop_event.is_set():
        raise InterruptedError("front door stopped")
    if hotkey_event is not None and hotkey_event.is_set():
        hotkey_event.clear()
        return "hotkey"
    return None


def _wait_from_frames(
    detector: WakeDetector,
    *,
    frames: Iterator[np.ndarray],
    hotkey_event: threading.Event | None,
    stop_event: threading.Event | None,
    poll_s: float,
) -> tuple[TriggerSource, Detection | None]:
    fl = detector.frame_length
    buf = np.zeros(0, dtype=np.int16)
    for chunk in frames:
        early = _drain_hotkey_or_stop(hotkey_event, stop_event)
        if early is not None:
            return early, None

        piece = np.asarray(chunk, dtype=np.int16).reshape(-1)
        if piece.size == 0:
            # Allow pure-event polling when the iterator yields empty chunks.
            if poll_s > 0:
                time.sleep(poll_s)
            continue
        buf = np.concatenate([buf, piece]) if buf.size else piece
        while buf.size >= fl:
            early = _drain_hotkey_or_stop(hotkey_event, stop_event)
            if early is not None:
                return early, None
            frame = buf[:fl]
            buf = buf[fl:]
            hit = detector.process(frame)
            if hit is not None:
                return "wake", hit

    # Frames exhausted — last chance for hotkey/stop.
    early = _drain_hotkey_or_stop(hotkey_event, stop_event)
    if early is not None:
        return early, None
    raise LookupError("frame source exhausted without wake or hotkey")


def _wait_from_mic(
    detector: WakeDetector,
    *,
    hotkey_event: threading.Event | None,
    stop_event: threading.Event | None,
    sample_rate: int,
) -> tuple[TriggerSource, Detection | None]:
    try:
        import sounddevice as sd
    except ImportError as e:
        raise RuntimeError(
            "sounddevice is required for wake listening. "
            'Install with: py -3.13 -m pip install -e ".[voice]"'
        ) from e

    fl = detector.frame_length
    q: queue.Queue[np.ndarray] = queue.Queue()

    def callback(indata, frames, time_info, status) -> None:  # noqa: ARG001
        q.put(indata.copy())

    stream = sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=max(fl, int(sample_rate * 0.03)),
        callback=callback,
    )
    stream.start()
    buf = np.zeros(0, dtype=np.int16)
    try:
        while True:
            early = _drain_hotkey_or_stop(hotkey_event, stop_event)
            if early is not None:
                return early, None
            try:
                block = q.get(timeout=0.15)
            except queue.Empty:
                continue
            i16 = float_to_int16(block)
            buf = np.concatenate([buf, i16]) if buf.size else i16
            while buf.size >= fl:
                early = _drain_hotkey_or_stop(hotkey_event, stop_event)
                if early is not None:
                    return early, None
                frame = buf[:fl]
                buf = buf[fl:]
                hit = detector.process(frame)
                if hit is not None:
                    return "wake", hit
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
