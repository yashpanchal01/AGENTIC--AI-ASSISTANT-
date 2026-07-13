"""Smart app open: focus existing window if running; launch only if needed."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.apps.catalog import AppSpec, default_catalog, resolve_app
from jarvis.apps.intents import AppIntentKind, classify
from jarvis.plain_replies import app_no_window_reply
from jarvis.reflex_humility import has_conversational_lead
from jarvis.types import Action


@dataclass
class AppResult:
    reply: str
    actions: tuple[Action, ...] = ()
    denied: bool = False
    ok: bool = True
    error: str | None = None


@dataclass
class AppHandler:
    """Voice-facing smart open.

    *ops* injects find/focus/launch for tests.
    """

    catalog: tuple[AppSpec, ...] = field(default_factory=default_catalog)
    ops: dict[str, Callable[..., Any]] = field(default_factory=dict)
    # Honest-outcome verification: after a launch, poll for a matching window up
    # to this bounded budget before claiming success (issue: fake "Done").
    verify_timeout_s: float = 2.5
    verify_poll_s: float = 0.25

    def _op(self, name: str, default: Callable[..., Any]) -> Callable[..., Any]:
        return self.ops.get(name, default)

    def try_handle(self, utterance: str) -> AppResult | None:
        # Reflex humility: a conversational request ("can you open brave for me")
        # is not a terse command — defer to the brain (mirrors the media reflex).
        if has_conversational_lead(utterance):
            return None

        intent = classify(utterance)
        if intent.kind is AppIntentKind.UNRELATED:
            return None

        spec = resolve_app(intent.app, self.catalog)
        if spec is None:
            # Unknown app — let the brain try a generic open.
            return None

        label = spec.spoken[0].title() if spec.spoken else spec.key

        if intent.kind is AppIntentKind.OPEN_NEW:
            return self._launch(spec, label, force_new=True)

        # OPEN or FOCUS: prefer existing window.
        win = self._find_window(spec)
        if win is not None:
            self._focus(win)
            return AppResult(
                reply=f"Focused {label}.",
                actions=(
                    Action(name="app_focus", detail=spec.key),
                ),
            )

        if intent.kind is AppIntentKind.FOCUS:
            return AppResult(
                reply=f"{label} isn't running.",
                ok=False,
                error="not_running",
            )

        # OPEN and nothing running → launch once.
        return self._launch(spec, label, force_new=False)

    def _find_window(self, spec: AppSpec) -> Any:
        find = self._op("find_windows", None)
        if find is None:
            from jarvis.windows.win32api import find_windows as _find

            find = _find
        for proc in spec.processes:
            hits = find(process=proc.lower())
            if hits:
                titled = [h for h in hits if getattr(h, "title", None)]
                return (titled or hits)[0]
        # Fallback: title contains app name (process name sometimes blank).
        for alias in spec.spoken:
            hits = find(title_substr=alias)
            if hits:
                return hits[0]
        # Last resort: any window whose title ends with " - Brave" style brand.
        brand = spec.spoken[0] if spec.spoken else spec.key
        hits = find(title_substr=f"- {brand}")
        if hits:
            return hits[0]
        return None

    def _focus(self, win: Any) -> None:
        focus_fn = self._op("focus", None)
        if focus_fn is None:
            from jarvis.windows.win32api import focus as _focus

            focus_fn = _focus
        hwnd = getattr(win, "hwnd", win)
        focus_fn(int(hwnd))

    def _launch(self, spec: AppSpec, label: str, *, force_new: bool) -> AppResult:
        launch = self._op("launch", _default_launch)
        try:
            launch(spec, force_new=force_new)
        except TypeError:
            # Test doubles may only accept spec.
            try:
                launch(spec)
            except Exception as exc:  # noqa: BLE001
                return AppResult(
                    reply=f"I couldn't open {label}.",
                    ok=False,
                    error=type(exc).__name__,
                )
        except Exception as exc:  # noqa: BLE001
            return AppResult(
                reply=f"I couldn't open {label}.",
                ok=False,
                error=type(exc).__name__,
            )

        # Honest outcome: don't claim success until a matching window shows up.
        if not self._verify_appeared(spec):
            return AppResult(
                reply=app_no_window_reply(label),
                ok=False,
                error="no_window",
                actions=(Action(name="app_launch_failed", detail=spec.key),),
            )

        detail = f"{spec.key}|new" if force_new else spec.key
        return AppResult(
            reply=f"Opened {label}." if not force_new else f"Opened a new {label} window.",
            actions=(Action(name="app_launch", detail=detail),),
        )

    def _verify_appeared(self, spec: AppSpec) -> bool:
        """Poll (bounded) for a window matching *spec* after a launch.

        Returns True as soon as one appears. Apps with no detectable process
        (URL / shell targets like ChatGPT or Windows Settings) can't be verified
        reliably, so we trust the launch rather than invent a false failure.
        """
        import time

        if not spec.processes:
            return True
        deadline = time.monotonic() + max(0.0, self.verify_timeout_s)
        while True:
            if self._find_window(spec) is not None:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(self.verify_poll_s)


# Chromium-family: bare startfile reuses the running instance; need --new-window.
_NEW_WINDOW_APPS = frozenset({"brave", "chrome", "edge"})


def _default_launch(spec: AppSpec, *, force_new: bool = False) -> None:
    """Start the app. If *force_new*, request a new window (browsers: --new-window)."""
    extra: tuple[str, ...] = ()
    if force_new and spec.key in _NEW_WINDOW_APPS:
        extra = ("--new-window",)

    for cand in spec.launch_candidates:
        if not cand:
            continue
        exe = cand[0]
        resolved: str | None = None
        if Path(exe).is_file():
            resolved = str(Path(exe))
        else:
            w = shutil.which(exe)
            if w:
                resolved = w
        if resolved is None:
            continue
        args = (resolved, *cand[1:], *extra)
        # startfile reuses single-instance apps — never for force_new.
        if (
            not force_new
            and sys.platform == "win32"
            and len(args) == 1
            and resolved.lower().endswith(".exe")
        ):
            os.startfile(resolved)  # type: ignore[attr-defined]
            return
        _popen(args)
        return

    if spec.shell_start and sys.platform == "win32":
        cmd = spec.shell_start
        if force_new and spec.key in _NEW_WINDOW_APPS:
            subprocess.Popen(
                ["cmd", "/c", "start", "", cmd, "--new-window"],
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["cmd", "/c", "start", "", cmd],
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return
    raise FileNotFoundError(spec.key)


def _popen(args: tuple[str, ...]) -> None:
    kwargs: dict[str, Any] = {
        "close_fds": True,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    # Do NOT use DETACHED_PROCESS for GUI apps — it can fail to show a window.
    subprocess.Popen(list(args), **kwargs)


def build_app_handler() -> AppHandler:
    return AppHandler()
