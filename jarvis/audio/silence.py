"""Silence / end-of-utterance detection (unit-testable, no microphone).

State machine:
  waiting_for_speech → (RMS above speech threshold) → in_speech
  in_speech → (RMS below silence threshold for silence_duration) → done

Matches the handoff target of ~0.5–1.0 s of trailing silence before ending.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

import numpy as np


class Phase(Enum):
    WAITING = auto()
    SPEAKING = auto()
    DONE = auto()


@dataclass(frozen=True)
class SilenceConfig:
    """Tunable thresholds for record-until-silence."""

    sample_rate: int = 16_000
    # RMS above this counts as speech (float32 samples in [-1, 1]).
    # Defaults tuned for quiet laptop arrays (Realtek often peaks ~0.01–0.03).
    speech_rms: float = 0.006
    # RMS below this counts as silence once speech has started.
    silence_rms: float = 0.004
    # How long silence must last after speech before we stop.
    silence_duration_s: float = 0.8
    # Give up if the user never starts speaking.
    max_lead_silence_s: float = 12.0
    # Hard cap on total capture length.
    max_record_s: float = 30.0
    # Ignore trailing-silence stop until at least this much speech audio.
    min_speech_s: float = 0.25


class SilenceTracker:
    """Feed audio blocks; query whether recording should stop."""

    def __init__(self, config: SilenceConfig | None = None) -> None:
        self.config = config or SilenceConfig()
        self.phase = Phase.WAITING
        self._samples_total = 0
        self._samples_speech = 0
        self._silence_run = 0

    @property
    def done(self) -> bool:
        return self.phase is Phase.DONE

    @property
    def heard_speech(self) -> bool:
        """True only if RMS crossed the speech threshold at least once."""
        return self._samples_speech > 0

    def feed(self, block: np.ndarray) -> Phase:
        """Ingest one mono float32 block; return current phase after update."""
        if self.phase is Phase.DONE:
            return self.phase

        flat = np.asarray(block, dtype=np.float32).reshape(-1)
        n = int(flat.size)
        if n == 0:
            return self.phase

        self._samples_total += n
        rms = float(np.sqrt(np.mean(np.square(flat))))
        cfg = self.config
        sr = cfg.sample_rate
        total_s = self._samples_total / sr

        if total_s >= cfg.max_record_s:
            self.phase = Phase.DONE
            return self.phase

        if self.phase is Phase.WAITING:
            if total_s >= cfg.max_lead_silence_s:
                self.phase = Phase.DONE
                return self.phase
            if rms >= cfg.speech_rms:
                self.phase = Phase.SPEAKING
                self._samples_speech += n
                self._silence_run = 0
            return self.phase

        # SPEAKING
        if rms >= cfg.silence_rms:
            self._samples_speech += n
            self._silence_run = 0
            return self.phase

        self._silence_run += n
        speech_s = self._samples_speech / sr
        silence_s = self._silence_run / sr
        if speech_s >= cfg.min_speech_s and silence_s >= cfg.silence_duration_s:
            self.phase = Phase.DONE
        return self.phase
