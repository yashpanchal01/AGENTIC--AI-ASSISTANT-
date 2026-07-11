#!/usr/bin/env python3
"""Standalone wake-word A/B bench: openWakeWord vs Porcupine on the real mic.

Issue 01 — not wired into the app. Local-only detection; audio never leaves the PC.

Usage (Windows):
  py -3.13 -m pip install -r benches/wake_word_ab/requirements.txt
  set PICOVOICE_ACCESS_KEY=...   # free key from https://console.picovoice.ai/
  py -3.13 benches/wake_word_ab/run_bench.py

Phases:
  1. Idle listen  — false-positive rate under room noise (both detectors, same audio)
  2. Prompted trials — true-positive / latency for each available detector
  3. Write results JSON + DECISION.md with a recommended pick

Optional flags let you shorten phases for a smoke check or re-run one side only.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import numpy as np

from detectors import (
    SAMPLE_RATE,
    WakeDetector,
    try_create_openwakeword,
    try_create_porcupine,
)
from metrics import (
    DetectionEvent,
    DetectorSummary,
    TrialResult,
    build_detector_summary,
    choose_winner,
)

DEFAULT_RESULTS_JSON = HERE / "results" / "latest.json"
DEFAULT_DECISION_MD = HERE / "DECISION.md"


def _beep() -> None:
    """Best-effort Windows console beep; silent elsewhere."""
    try:
        import winsound

        winsound.Beep(880, 120)
    except Exception:
        print("\a", end="", flush=True)


def _prompt(msg: str) -> str:
    try:
        return input(msg)
    except EOFError:
        return ""


def _audio_float_to_i16(block: np.ndarray) -> np.ndarray:
    """sounddevice float32 [-1,1] → int16 PCM."""
    clipped = np.clip(block.reshape(-1), -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


class MicFanout:
    """Capture 16 kHz mono mic audio and feed each detector its own frame size."""

    def __init__(self, detectors: list[WakeDetector], device: int | None = None):
        import sounddevice as sd

        self._sd = sd
        self._detectors = detectors
        self._device = device
        self._buffers: dict[str, np.ndarray] = {
            d.name: np.zeros(0, dtype=np.int16) for d in detectors
        }
        self._lock = threading.Lock()
        self._events: list[DetectionEvent] = []
        self._arm_prompt_t: dict[str, float | None] = {
            d.name: None for d in detectors
        }
        self._armed_for_trial: set[str] = set()
        self._stream: Any = None
        self._running = False
        # Cooldown so a single utterance doesn't multi-fire
        self._last_fire: dict[str, float] = {d.name: 0.0 for d in detectors}
        self._cooldown_s = 1.2

    def start(self) -> None:
        block = 512  # samples; both engines can be fed from smaller mic blocks

        def callback(indata, frames, time_info, status):  # noqa: ARG001
            if status:
                # Non-fatal under/overflow notes from PortAudio
                pass
            pcm = _audio_float_to_i16(indata)
            with self._lock:
                for det in self._detectors:
                    buf = np.concatenate([self._buffers[det.name], pcm])
                    fl = det.frame_length
                    while len(buf) >= fl:
                        frame = buf[:fl]
                        buf = buf[fl:]
                        try:
                            hit = det.process(frame)
                        except Exception as exc:  # keep stream alive
                            print(
                                f"[{det.name}] process error: {exc}",
                                file=sys.stderr,
                            )
                            hit = None
                        if hit is None:
                            continue
                        # Timestamp at the frame that fired, not once per callback.
                        now = time.monotonic()
                        if now - self._last_fire[det.name] < self._cooldown_s:
                            continue
                        self._last_fire[det.name] = now
                        latency = None
                        prompt_t = self._arm_prompt_t.get(det.name)
                        if (
                            det.name in self._armed_for_trial
                            and prompt_t is not None
                        ):
                            latency = now - prompt_t
                        self._events.append(
                            DetectionEvent(
                                detector=det.name,
                                t_mono=now,
                                score=hit.score,
                                latency_s=latency,
                            )
                        )
                    self._buffers[det.name] = buf

        self._stream = self._sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=block,
            device=self._device,
            callback=callback,
        )
        self._stream.start()
        self._running = True

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def drain_events(self) -> list[DetectionEvent]:
        with self._lock:
            out = list(self._events)
            self._events.clear()
            return out

    def arm_trial(self, detector_name: str) -> float:
        t = time.monotonic()
        with self._lock:
            self._arm_prompt_t[detector_name] = t
            self._armed_for_trial.add(detector_name)
            # Drop stale events so prior noise doesn't count as a hit
            self._events = [
                e for e in self._events if e.detector != detector_name
            ]
            # Drop residual PCM so a prior partial frame can't fire instantly
            if detector_name in self._buffers:
                self._buffers[detector_name] = np.zeros(0, dtype=np.int16)
            # Reset multi-fire cooldown so back-to-back trials aren't blocked
            self._last_fire[detector_name] = 0.0
        # Best-effort reset of detector-internal prediction history
        for det in self._detectors:
            if det.name == detector_name and hasattr(det, "reset"):
                try:
                    det.reset()  # type: ignore[attr-defined]
                except Exception:
                    pass
        return t

    def disarm_trial(self, detector_name: str) -> None:
        with self._lock:
            self._armed_for_trial.discard(detector_name)
            self._arm_prompt_t[detector_name] = None


def run_false_positive_phase(
    fanout: MicFanout,
    detectors: list[WakeDetector],
    listen_s: float,
) -> dict[str, list[DetectionEvent]]:
    print()
    print("=" * 60)
    print("PHASE 1 — False positives (room noise / normal speech)")
    print("=" * 60)
    print(
        f"Stay quiet or talk normally, but do NOT say the wake phrases "
        f"({', '.join(repr(d.phrase) for d in detectors)})."
    )
    print(f"Listening for {listen_s:.0f}s …")
    _beep()
    fanout.drain_events()
    end = time.monotonic() + listen_s
    while time.monotonic() < end:
        remaining = end - time.monotonic()
        print(f"  {remaining:5.1f}s left", end="\r", flush=True)
        time.sleep(0.2)
    print()
    events = fanout.drain_events()
    by_det: dict[str, list[DetectionEvent]] = {d.name: [] for d in detectors}
    for e in events:
        by_det.setdefault(e.detector, []).append(e)
    for d in detectors:
        print(f"  {d.name}: {len(by_det[d.name])} false positive(s)")
    return by_det


def run_trial_phase(
    fanout: MicFanout,
    detector: WakeDetector,
    n_trials: int,
    timeout_s: float,
) -> list[TrialResult]:
    print()
    print("=" * 60)
    print(f"PHASE 2 — True-positive trials: {detector.name}")
    print("=" * 60)
    print(f'When prompted, say: "{detector.phrase}"')
    print(f"Trials: {n_trials}  |  timeout per trial: {timeout_s:.1f}s")
    results: list[TrialResult] = []

    for i in range(1, n_trials + 1):
        _prompt(f"\n[{detector.name} {i}/{n_trials}] Press Enter, then say "
                f'"{detector.phrase}" immediately… ')
        _beep()
        fanout.arm_trial(detector.name)
        deadline = time.monotonic() + timeout_s
        hit: DetectionEvent | None = None
        while time.monotonic() < deadline:
            for e in fanout.drain_events():
                if e.detector == detector.name and e.latency_s is not None:
                    hit = e
                    break
            if hit is not None:
                break
            time.sleep(0.03)
        fanout.disarm_trial(detector.name)
        # Discard leftover events from other detectors during this trial
        fanout.drain_events()

        if hit is not None and hit.latency_s is not None:
            print(
                f"  HIT  latency={hit.latency_s*1000:.0f} ms"
                + (f"  score={hit.score:.3f}" if hit.score is not None else "")
            )
            results.append(
                TrialResult(
                    detector=detector.name,
                    trial_index=i,
                    detected=True,
                    latency_s=hit.latency_s,
                    timeout_s=timeout_s,
                )
            )
        else:
            print("  MISS (timeout)")
            results.append(
                TrialResult(
                    detector=detector.name,
                    trial_index=i,
                    detected=False,
                    latency_s=None,
                    timeout_s=timeout_s,
                )
            )
    return results


def render_decision_md(
    *,
    summaries: list[DetectorSummary],
    winner: str | None,
    rationale: str,
    extra_notes: str,
    generated_at: str,
) -> str:
    lines = [
        "# Wake-word detector decision (issue 01)",
        "",
        f"Generated: {generated_at}",
        "",
        "Standalone A/B bench on this machine's real microphone. "
        "Local-only detection — no audio leaves the PC.",
        "",
        "## Recommendation",
        "",
    ]
    if winner:
        lines.append(f"**Winner: {winner}**")
        lines.append("")
        lines.append(rationale)
    else:
        lines.append("**No automatic winner** — see notes.")
        lines.append("")
        lines.append(rationale)
    lines += ["", "## Results", ""]

    for s in summaries:
        lines.append(f"### {s.name}")
        lines.append("")
        if not s.available:
            lines.append(f"- **Unavailable:** {s.skip_reason}")
            lines.append("")
            continue
        lines.append(f"- **Phrase:** `{s.phrase}`")
        lines.append(
            f"- **False positives:** {s.false_positives} "
            f"in {s.fp_listen_s:.0f}s"
            + (
                f" (≈ {s.fp_per_hour:.1f}/hour)"
                if s.fp_per_hour is not None
                else ""
            )
        )
        if s.trials:
            hr = f"{s.hit_rate:.0%}" if s.hit_rate is not None else "n/a"
            lines.append(
                f"- **True positives:** {s.hits}/{s.trials} hits ({hr}), "
                f"{s.misses} miss(es)"
            )
            if s.latencies_s:
                lines.append(
                    f"- **Latency (s):** mean={s.latency_mean_s:.3f}, "
                    f"median={s.latency_median_s:.3f}, "
                    f"min={s.latency_min_s:.3f}, max={s.latency_max_s:.3f}"
                )
                ms = ", ".join(f"{x*1000:.0f}" for x in s.latencies_s)
                lines.append(f"- **Latency samples (ms):** {ms}")
        if s.qualitative_notes:
            lines.append(f"- **Notes:** {'; '.join(s.qualitative_notes)}")
        lines.append("")

    lines += [
        "## Product notes",
        "",
        "- openWakeWord's bundled model is **\"hey jarvis\"** (two words).",
        "- Porcupine ships a prebuilt **\"jarvis\"** keyword (matches PRD phrasing).",
        "- Porcupine needs a free Picovoice access key (`PICOVOICE_ACCESS_KEY`).",
        "- Windows SAPI and browser speech are already rejected (see PRD).",
        "",
        "## Operator notes",
        "",
        extra_notes.strip() or "_(none)_",
        "",
        "## How to re-run",
        "",
        "```text",
        "py -3.13 -m pip install -r benches/wake_word_ab/requirements.txt",
        "set PICOVOICE_ACCESS_KEY=your_key_here",
        "py -3.13 benches/wake_word_ab/run_bench.py",
        "```",
        "",
        "Smoke (short):",
        "",
        "```text",
        "py -3.13 benches/wake_word_ab/run_bench.py --fp-seconds 15 --trials 3",
        "```",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="A/B bench: openWakeWord vs Porcupine for 'Jarvis' wake word"
    )
    p.add_argument(
        "--fp-seconds",
        type=float,
        default=60.0,
        help="False-positive listen duration in seconds (default 60)",
    )
    p.add_argument(
        "--trials",
        type=int,
        default=8,
        help="Prompted true-positive trials per detector (default 8)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=4.0,
        help="Seconds to wait for a detection after each prompt (default 4)",
    )
    p.add_argument(
        "--device",
        type=int,
        default=None,
        help="sounddevice input device index (default: system default)",
    )
    p.add_argument(
        "--skip-openwakeword",
        action="store_true",
        help="Do not load openWakeWord",
    )
    p.add_argument(
        "--skip-porcupine",
        action="store_true",
        help="Do not load Porcupine",
    )
    p.add_argument(
        "--oww-threshold",
        type=float,
        default=0.5,
        help="openWakeWord activation threshold (default 0.5)",
    )
    p.add_argument(
        "--porcupine-sensitivity",
        type=float,
        default=0.5,
        help="Porcupine sensitivity 0..1 (default 0.5)",
    )
    p.add_argument(
        "--results-json",
        type=Path,
        default=DEFAULT_RESULTS_JSON,
        help="Where to write machine-readable results",
    )
    p.add_argument(
        "--decision-md",
        type=Path,
        default=DEFAULT_DECISION_MD,
        help="Where to write the human decision doc",
    )
    p.add_argument(
        "--list-devices",
        action="store_true",
        help="Print input devices and exit",
    )
    p.add_argument(
        "--no-interactive-notes",
        action="store_true",
        help="Skip free-text qualitative note prompts at the end",
    )
    p.add_argument(
        "--force-decision",
        action="store_true",
        help=(
            "Overwrite DECISION.md even if only one detector completed trials "
            "(default: require both engines)"
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return 0

    print("JARVIS wake-word A/B bench")
    print("Local-only detection — audio stays on this PC.")
    print()

    created: list[WakeDetector] = []
    skip: dict[str, str] = {}
    phrases: dict[str, str] = {
        "openWakeWord": "hey jarvis",
        "Porcupine": "jarvis",
    }

    if not args.skip_openwakeword:
        print("Loading openWakeWord…")
        det, err = try_create_openwakeword(threshold=args.oww_threshold)
        if det:
            created.append(det)
            print(f"  ok  phrase={det.phrase!r} frame={det.frame_length}")
        else:
            skip["openWakeWord"] = err
            print(f"  SKIP: {err}")
    else:
        skip["openWakeWord"] = "skipped by flag"

    if not args.skip_porcupine:
        print("Loading Porcupine…")
        det, err = try_create_porcupine(sensitivity=args.porcupine_sensitivity)
        if det:
            created.append(det)
            print(f"  ok  phrase={det.phrase!r} frame={det.frame_length}")
        else:
            skip["Porcupine"] = err
            print(f"  SKIP: {err}")
    else:
        skip["Porcupine"] = "skipped by flag"

    if not created:
        print(
            "\nNo detectors available. Install deps and set PICOVOICE_ACCESS_KEY "
            "for Porcupine.",
            file=sys.stderr,
        )
        return 1

    fanout = MicFanout(created, device=args.device)
    fp_by_det: dict[str, list[DetectionEvent]] = {}
    trials_by_det: dict[str, list[TrialResult]] = {}
    notes_by_det: dict[str, list[str]] = {d.name: [] for d in created}

    try:
        print("\nOpening microphone…")
        fanout.start()
        print("Mic open.")

        if args.fp_seconds > 0:
            fp_by_det = run_false_positive_phase(
                fanout, created, args.fp_seconds
            )
        else:
            fp_by_det = {d.name: [] for d in created}

        for det in created:
            if args.trials > 0:
                trials_by_det[det.name] = run_trial_phase(
                    fanout, det, args.trials, args.timeout
                )
            else:
                trials_by_det[det.name] = []

        if not args.no_interactive_notes:
            print()
            print("=" * 60)
            print("Qualitative notes (Enter to skip each)")
            print("=" * 60)
            for det in created:
                note = _prompt(
                    f"Notes for {det.name} (noise, distance, quirks): "
                ).strip()
                if note:
                    notes_by_det[det.name].append(note)
            global_note = _prompt(
                "Any overall room/mic notes for the decision doc: "
            ).strip()
        else:
            global_note = ""
    finally:
        fanout.stop()
        for det in created:
            det.close()

    # Build summaries for available + skipped
    summaries: list[DetectorSummary] = []
    all_names = ["openWakeWord", "Porcupine"]
    available_map = {d.name: d for d in created}
    for name in all_names:
        if name in available_map:
            d = available_map[name]
            summaries.append(
                build_detector_summary(
                    name=name,
                    phrase=d.phrase,
                    available=True,
                    fp_listen_s=args.fp_seconds,
                    fp_events=fp_by_det.get(name, []),
                    trials=trials_by_det.get(name, []),
                    qualitative_notes=notes_by_det.get(name, []),
                )
            )
        else:
            summaries.append(
                build_detector_summary(
                    name=name,
                    phrase=phrases[name],
                    available=False,
                    skip_reason=skip.get(name, "unknown"),
                )
            )

    winner, rationale = choose_winner(summaries)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    payload = {
        "generated_at": generated_at,
        "config": {
            "fp_seconds": args.fp_seconds,
            "trials": args.trials,
            "timeout": args.timeout,
            "oww_threshold": args.oww_threshold,
            "porcupine_sensitivity": args.porcupine_sensitivity,
            "device": args.device,
        },
        "winner": winner,
        "rationale": rationale,
        "summaries": [s.to_dict() for s in summaries],
        "operator_notes": global_note,
    }

    args.results_json.parent.mkdir(parents=True, exist_ok=True)
    args.results_json.write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    # Only overwrite DECISION.md when BOTH engines finished at least one trial
    # (or the user forces it). Prevents one-sided smokes from clobbering the
    # provisional product pick in DECISION.md.
    available_with_trials = [
        s for s in summaries if s.available and s.trials > 0
    ]
    force = bool(getattr(args, "force_decision", False))
    wrote_decision = False
    if force or len(available_with_trials) >= 2:
        md = render_decision_md(
            summaries=summaries,
            winner=winner,
            rationale=rationale,
            extra_notes=global_note,
            generated_at=generated_at,
        )
        args.decision_md.write_text(md, encoding="utf-8")
        wrote_decision = True

    print()
    print("=" * 60)
    print("DONE")
    print("=" * 60)
    if winner:
        print(f"Recommendation: {winner}")
    else:
        print("Recommendation: (none — incomplete run)")
    print(rationale)
    print(f"Results JSON: {args.results_json}")
    if wrote_decision:
        print(f"Decision doc: {args.decision_md}")
    else:
        print(
            f"Decision doc unchanged (no trials completed): {args.decision_md}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
