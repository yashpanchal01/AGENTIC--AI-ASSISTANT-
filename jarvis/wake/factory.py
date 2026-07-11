"""Choose a local wake detector: Porcupine if key present, else openWakeWord."""

from __future__ import annotations

import os
from typing import Any

from jarvis.wake.base import WakeDetector


def picovoice_key_present(access_key: str | None = None) -> bool:
    key = (access_key if access_key is not None else os.environ.get("PICOVOICE_ACCESS_KEY", "")).strip()
    return bool(key)


def create_wake_detector(
    *,
    access_key: str | None = None,
    threshold: float = 0.5,
    sensitivity: float = 0.5,
    prefer: str | None = None,
) -> WakeDetector:
    """Build the best available local detector.

    Order:
      1. Porcupine when PICOVOICE_ACCESS_KEY is set (or access_key=) and import works
      2. openWakeWord fallback
      3. RuntimeError with a clear install / key message

    prefer: force "porcupine" | "openwakeword" (still fails clearly if unavailable).
    """
    prefer_norm = (prefer or "").strip().lower() or None
    key = (access_key if access_key is not None else os.environ.get("PICOVOICE_ACCESS_KEY", "")).strip()

    errors: list[str] = []

    def try_porcupine() -> WakeDetector | None:
        try:
            from jarvis.wake.detectors import PorcupineDetector

            return PorcupineDetector(access_key=key or None, sensitivity=sensitivity)
        except Exception as exc:  # noqa: BLE001 — factory must degrade gracefully
            errors.append(f"Porcupine: {type(exc).__name__}: {exc}")
            return None

    def try_oww() -> WakeDetector | None:
        try:
            from jarvis.wake.detectors import OpenWakeWordDetector

            return OpenWakeWordDetector(threshold=threshold)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"openWakeWord: {type(exc).__name__}: {exc}")
            return None

    if prefer_norm in ("porcupine", "pvporcupine", "pv"):
        det = try_porcupine()
        if det is not None:
            return det
        raise RuntimeError(
            "Requested Porcupine wake detector is unavailable.\n"
            + "\n".join(errors)
            + "\nSet PICOVOICE_ACCESS_KEY and: py -3.13 -m pip install -e \".[wake]\""
        )

    if prefer_norm in ("openwakeword", "oww", "open"):
        det = try_oww()
        if det is not None:
            return det
        raise RuntimeError(
            "Requested openWakeWord detector is unavailable.\n"
            + "\n".join(errors)
            + "\nInstall with: py -3.13 -m pip install -e \".[wake]\""
        )

    # Auto: Porcupine first when a key is present.
    if key:
        det = try_porcupine()
        if det is not None:
            return det

    det = try_oww()
    if det is not None:
        return det

    # Last chance: Porcupine without prior key check (user may have passed key via prefer path)
    if not key:
        det = try_porcupine()
        if det is not None:
            return det

    detail = "\n".join(errors) if errors else "no detectors attempted"
    raise RuntimeError(
        "No local wake-word detector available.\n"
        f"{detail}\n"
        "Install wake extras: py -3.13 -m pip install -e \".[wake]\"\n"
        "Optional Porcupine: set PICOVOICE_ACCESS_KEY (https://console.picovoice.ai/)."
    )


def try_create_wake_detector(**kwargs: Any) -> tuple[WakeDetector | None, str]:
    """Like create_wake_detector but returns (detector, error) instead of raising."""
    try:
        return create_wake_detector(**kwargs), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
