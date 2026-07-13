"""Voice-facing system controls: classify → brightness / latest-capture.

Same result shape as the other slices (reply/actions/ok/error) so
:func:`jarvis.core._finish_handler` speaks it and the audit log records it.
Both verbs are non-destructive — no confirm gate — but every action is
audit-logged like the rest of the pipeline (the core dispatch does that).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.plain_replies import plain_error_reply
from jarvis.system.brightness import (
    BrightnessError,
    UNSUPPORTED_MESSAGE,
    clamp,
    default_get_brightness,
    default_set_brightness,
)
from jarvis.system.intents import SystemIntentKind, classify
from jarvis.types import Action

# Screen recordings / captures are video — filter the folder scan to these.
VIDEO_EXTS: frozenset[str] = frozenset(
    {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".gif"}
)

GetBrightnessFn = Callable[[], int]
SetBrightnessFn = Callable[[int], None]
OpenFn = Callable[[Path], None]


@dataclass
class SystemResult:
    reply: str
    actions: tuple[Action, ...] = ()
    denied: bool = False
    ok: bool = True
    error: str | None = None


def _default_open(path: Path) -> None:
    # Reuse the media slice's real OS open (VLC/default app) — never a fake.
    from jarvis.media.handler import default_open

    default_open(path)


def find_latest(roots: tuple[Path, ...], exts: frozenset[str]) -> Path | None:
    """Newest-by-mtime file across *roots* whose suffix is in *exts*."""
    best: Path | None = None
    best_mtime = -1.0
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for p in entries:
            if not p.is_file():
                continue
            if p.suffix.lower() not in exts:
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if mtime > best_mtime:
                best, best_mtime = p, mtime
    return best


@dataclass
class SystemHandler:
    """classify → set/step brightness, or open the newest capture.

    ``get_brightness`` / ``set_brightness`` / ``open_fn`` are injected so tests
    can fake both the WMI success and unsupported-panel paths without touching
    the real display.
    """

    capture_roots: tuple[Path, ...] = field(default_factory=tuple)
    get_brightness: GetBrightnessFn = default_get_brightness
    set_brightness: SetBrightnessFn = default_set_brightness
    open_fn: OpenFn = _default_open
    capture_exts: frozenset[str] = VIDEO_EXTS

    def try_handle(self, utterance: str) -> SystemResult | None:
        intent = classify(utterance)
        if intent.kind is SystemIntentKind.UNRELATED:
            return None
        if intent.kind is SystemIntentKind.BRIGHTNESS_SET:
            return self._set_brightness(clamp(intent.level or 0))
        if intent.kind is SystemIntentKind.BRIGHTNESS_STEP:
            return self._step_brightness(int(intent.delta or 0))
        if intent.kind is SystemIntentKind.LATEST_CAPTURE:
            return self._open_latest(intent.category)
        return None

    # -- brightness ---------------------------------------------------------

    def _set_brightness(self, level: int) -> SystemResult:
        try:
            self.set_brightness(level)
        except BrightnessError as exc:
            return self._brightness_failure(exc)
        except Exception as exc:  # noqa: BLE001 — boundary: speak plain, never crash
            return SystemResult(
                reply=UNSUPPORTED_MESSAGE, ok=False, error=type(exc).__name__
            )
        return SystemResult(
            reply=f"Brightness set to {level} percent.",
            actions=(Action(name="brightness_set", detail=str(level)),),
        )

    def _step_brightness(self, delta: int) -> SystemResult:
        try:
            current = int(self.get_brightness())
            target = clamp(current + delta)
            self.set_brightness(target)
        except BrightnessError as exc:
            return self._brightness_failure(exc)
        except Exception as exc:  # noqa: BLE001 — boundary
            return SystemResult(
                reply=UNSUPPORTED_MESSAGE, ok=False, error=type(exc).__name__
            )
        direction = "up" if delta >= 0 else "down"
        return SystemResult(
            reply=f"Brightness {direction} to {target} percent.",
            actions=(Action(name="brightness_set", detail=str(target)),),
        )

    @staticmethod
    def _brightness_failure(exc: BrightnessError) -> SystemResult:
        # Plain-language spoken message (plain_replies), never a stack trace.
        reply = str(exc).strip() or plain_error_reply(
            "brightness_unsupported", fallback=UNSUPPORTED_MESSAGE
        )
        return SystemResult(reply=reply, ok=False, error="brightness_unsupported")

    # -- latest capture -----------------------------------------------------

    def _open_latest(self, category: str) -> SystemResult:
        path = find_latest(self.capture_roots, self.capture_exts)
        if path is None:
            return SystemResult(
                reply=(
                    f"I couldn't find a {category} in your capture folders."
                ),
                ok=False,
                error="not_found",
            )
        try:
            self.open_fn(path)
        except Exception as exc:  # noqa: BLE001 — boundary
            return SystemResult(
                reply=f"I found {path.name} but couldn't open it.",
                ok=False,
                error=type(exc).__name__,
            )
        return SystemResult(
            reply=f"Opening {path.name}.",
            actions=(Action(name="latest_capture_open", detail=str(path)),),
        )


def build_system_handler(config: Any = None) -> SystemHandler:
    """Wire the system handler from config's capture folders (settings-driven)."""
    roots: tuple[Path, ...] = ()
    if config is not None:
        roots = tuple(Path(p) for p in getattr(config, "capture_folders", ()) or ())
    return SystemHandler(capture_roots=roots)
