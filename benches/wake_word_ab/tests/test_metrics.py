"""Unit tests for wake-word bench metrics (no mic required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from metrics import (  # noqa: E402
    DetectionEvent,
    TrialResult,
    build_detector_summary,
    choose_winner,
    summarize_false_positives,
    summarize_trials,
)


class TestFalsePositives(unittest.TestCase):
    def test_per_hour_scaling(self) -> None:
        events = [
            DetectionEvent(detector="A", t_mono=1.0),
            DetectionEvent(detector="A", t_mono=2.0),
        ]
        count, per_hour = summarize_false_positives(listen_s=60.0, events=events)
        self.assertEqual(count, 2)
        self.assertAlmostEqual(per_hour, 120.0)

    def test_zero_listen(self) -> None:
        count, per_hour = summarize_false_positives(listen_s=0.0, events=[])
        self.assertEqual(count, 0)
        self.assertIsNone(per_hour)


class TestTrials(unittest.TestCase):
    def test_hit_rate_and_latency(self) -> None:
        trials = [
            TrialResult("A", 1, True, 0.4, 4.0),
            TrialResult("A", 2, True, 0.6, 4.0),
            TrialResult("A", 3, False, None, 4.0),
        ]
        stats = summarize_trials(trials)
        self.assertEqual(stats["hits"], 2)
        self.assertEqual(stats["misses"], 1)
        self.assertAlmostEqual(stats["hit_rate"], 2 / 3)
        self.assertAlmostEqual(stats["latency_mean_s"], 0.5)
        self.assertAlmostEqual(stats["latency_median_s"], 0.5)


class TestChooseWinner(unittest.TestCase):
    def test_prefers_higher_hit_rate(self) -> None:
        a = build_detector_summary(
            name="openWakeWord",
            phrase="hey jarvis",
            available=True,
            fp_listen_s=60,
            fp_events=[],
            trials=[
                TrialResult("openWakeWord", 1, True, 0.5, 4.0),
                TrialResult("openWakeWord", 2, False, None, 4.0),
            ],
        )
        b = build_detector_summary(
            name="Porcupine",
            phrase="jarvis",
            available=True,
            fp_listen_s=60,
            fp_events=[],
            trials=[
                TrialResult("Porcupine", 1, True, 0.5, 4.0),
                TrialResult("Porcupine", 2, True, 0.6, 4.0),
            ],
        )
        winner, rationale = choose_winner([a, b])
        self.assertEqual(winner, "Porcupine")
        self.assertIn("Porcupine", rationale)

    def test_latency_tiebreak(self) -> None:
        slow = build_detector_summary(
            name="openWakeWord",
            phrase="hey jarvis",
            available=True,
            trials=[TrialResult("openWakeWord", 1, True, 0.9, 4.0)],
        )
        fast = build_detector_summary(
            name="Porcupine",
            phrase="jarvis",
            available=True,
            trials=[TrialResult("Porcupine", 1, True, 0.2, 4.0)],
        )
        winner, _ = choose_winner([slow, fast])
        self.assertEqual(winner, "Porcupine")

    def test_phrase_tiebreak_prefers_jarvis(self) -> None:
        oww = build_detector_summary(
            name="openWakeWord",
            phrase="hey jarvis",
            available=True,
            trials=[TrialResult("openWakeWord", 1, True, 0.3, 4.0)],
        )
        porc = build_detector_summary(
            name="Porcupine",
            phrase="jarvis",
            available=True,
            trials=[TrialResult("Porcupine", 1, True, 0.3, 4.0)],
        )
        winner, _ = choose_winner([oww, porc])
        self.assertEqual(winner, "Porcupine")

    def test_no_candidates(self) -> None:
        skipped = build_detector_summary(
            name="Porcupine",
            phrase="jarvis",
            available=False,
            skip_reason="no key",
        )
        winner, rationale = choose_winner([skipped])
        self.assertIsNone(winner)
        self.assertIn("cannot pick", rationale.lower())


if __name__ == "__main__":
    unittest.main()
