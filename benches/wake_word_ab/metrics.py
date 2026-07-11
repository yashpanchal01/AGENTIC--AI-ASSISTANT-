"""Pure stats for the wake-word A/B bench (no audio I/O).

Seam: aggregate trial/false-positive events into summary numbers used by the
report writer. Unit-testable without a microphone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import mean, median
from typing import Any


@dataclass
class DetectionEvent:
    """One positive detection during a timed phase."""

    detector: str
    t_mono: float  # time.monotonic() when the detector fired
    score: float | None = None
    latency_s: float | None = None  # only for prompted true-positive trials


@dataclass
class TrialResult:
    """One prompted true-positive attempt."""

    detector: str
    trial_index: int
    detected: bool
    latency_s: float | None
    timeout_s: float
    note: str = ""


@dataclass
class DetectorSummary:
    name: str
    phrase: str
    available: bool
    skip_reason: str = ""
    # False-positive phase
    fp_listen_s: float = 0.0
    false_positives: int = 0
    fp_per_hour: float | None = None
    # True-positive / latency phase
    trials: int = 0
    hits: int = 0
    misses: int = 0
    hit_rate: float | None = None
    latencies_s: list[float] = field(default_factory=list)
    latency_mean_s: float | None = None
    latency_median_s: float | None = None
    latency_min_s: float | None = None
    latency_max_s: float | None = None
    qualitative_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_false_positives(
    *,
    listen_s: float,
    events: list[DetectionEvent],
) -> tuple[int, float | None]:
    """Return (count, false-positives-per-hour estimate)."""
    if listen_s < 0:
        raise ValueError("listen_s must be non-negative")
    count = len(events)
    if listen_s <= 0:
        return count, None
    per_hour = count * (3600.0 / listen_s)
    return count, per_hour


def summarize_trials(trials: list[TrialResult]) -> dict[str, Any]:
    """Aggregate prompted trials into hit/miss and latency stats."""
    hits = [t for t in trials if t.detected]
    misses = [t for t in trials if not t.detected]
    latencies = [
        t.latency_s for t in hits if t.latency_s is not None
    ]
    n = len(trials)
    return {
        "trials": n,
        "hits": len(hits),
        "misses": len(misses),
        "hit_rate": (len(hits) / n) if n else None,
        "latencies_s": latencies,
        "latency_mean_s": mean(latencies) if latencies else None,
        "latency_median_s": median(latencies) if latencies else None,
        "latency_min_s": min(latencies) if latencies else None,
        "latency_max_s": max(latencies) if latencies else None,
    }


def build_detector_summary(
    *,
    name: str,
    phrase: str,
    available: bool,
    skip_reason: str = "",
    fp_listen_s: float = 0.0,
    fp_events: list[DetectionEvent] | None = None,
    trials: list[TrialResult] | None = None,
    qualitative_notes: list[str] | None = None,
) -> DetectorSummary:
    summary = DetectorSummary(
        name=name,
        phrase=phrase,
        available=available,
        skip_reason=skip_reason,
        qualitative_notes=list(qualitative_notes or []),
    )
    if not available:
        return summary

    fp_events = fp_events or []
    trials = trials or []
    count, per_hour = summarize_false_positives(
        listen_s=fp_listen_s, events=fp_events
    )
    summary.fp_listen_s = fp_listen_s
    summary.false_positives = count
    summary.fp_per_hour = per_hour

    stats = summarize_trials(trials)
    summary.trials = stats["trials"]
    summary.hits = stats["hits"]
    summary.misses = stats["misses"]
    summary.hit_rate = stats["hit_rate"]
    summary.latencies_s = stats["latencies_s"]
    summary.latency_mean_s = stats["latency_mean_s"]
    summary.latency_median_s = stats["latency_median_s"]
    summary.latency_min_s = stats["latency_min_s"]
    summary.latency_max_s = stats["latency_max_s"]
    return summary


def choose_winner(
    summaries: list[DetectorSummary],
) -> tuple[str | None, str]:
    """Pick a detector from summaries using simple, documented rules.

    Rules (in order):
    1. Only consider available detectors that completed at least one trial.
    2. Prefer higher hit_rate (true-positive rate).
    3. Break ties with lower median latency.
    4. Break remaining ties with fewer false positives per hour.
    5. Prefer the single-word "jarvis" phrase over multi-word when still tied
       (matches the product wake phrase in the PRD).
    """
    candidates = [
        s
        for s in summaries
        if s.available and s.trials > 0 and s.hit_rate is not None
    ]
    if not candidates:
        return None, "No detector completed trials; cannot pick a winner."

    def sort_key(s: DetectorSummary) -> tuple:
        hit = s.hit_rate if s.hit_rate is not None else -1.0
        med = (
            s.latency_median_s
            if s.latency_median_s is not None
            else float("inf")
        )
        fph = s.fp_per_hour if s.fp_per_hour is not None else float("inf")
        # Prefer single-token product phrase ("jarvis") over "hey jarvis"
        phrase_penalty = 0 if s.phrase.strip().lower() == "jarvis" else 1
        return (-hit, med, fph, phrase_penalty, s.name)

    ordered = sorted(candidates, key=sort_key)
    winner = ordered[0]
    reasons = [
        f"hit_rate={winner.hit_rate:.0%}" if winner.hit_rate is not None else "",
        (
            f"median_latency={winner.latency_median_s*1000:.0f}ms"
            if winner.latency_median_s is not None
            else ""
        ),
        (
            f"fp/hour≈{winner.fp_per_hour:.1f}"
            if winner.fp_per_hour is not None
            else ""
        ),
        f'phrase="{winner.phrase}"',
    ]
    rationale = (
        f"Chose **{winner.name}** "
        f"({', '.join(r for r in reasons if r)}). "
        "Ordering: highest hit rate, then lowest median latency, then lowest "
        "false-positive rate, then prefer the product phrase 'jarvis'."
    )
    return winner.name, rationale
