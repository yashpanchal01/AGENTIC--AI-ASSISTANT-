"""Voice-facing window control: classify → Win32 action."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from jarvis.types import Action
from jarvis.windows.intents import WindowIntentKind, classify
from jarvis.windows.win32api import (
    WindowError,
    WindowInfo,
    close,
    find_windows,
    focus,
    fullscreen_media_player,
    maximize,
    minimize,
    minimize_all,
    restore,
    snap_half,
    snap_media_player,
    wait_for_window,
)


@dataclass
class WindowResult:
    reply: str
    actions: tuple[Action, ...] = ()
    denied: bool = False
    ok: bool = True
    error: str | None = None


_ALIASES: dict[str, tuple[str, ...]] = {
    "vlc": ("vlc",),
    "spotify": ("spotify",),
    "chrome": ("chrome", "msedge"),
    "edge": ("msedge", "chrome"),
    "browser": ("chrome", "msedge", "firefox"),
    "firefox": ("firefox",),
    "notepad": ("notepad",),
    "terminal": ("windowsterminal", "cmd", "powershell"),
    "code": ("code",),
    "vs code": ("code",),
    "discord": ("discord",),
}


@dataclass
class WindowHandler:
    ops: dict[str, Callable[..., Any]] = field(default_factory=dict)

    def _op(self, name: str, default: Callable[..., Any]) -> Callable[..., Any]:
        return self.ops.get(name, default)

    def try_handle(self, utterance: str) -> WindowResult | None:
        intent = classify(utterance)
        if intent.kind is WindowIntentKind.UNRELATED:
            return None
        try:
            return self._dispatch(intent.kind, intent.target, intent.snap)
        except WindowError as exc:
            return WindowResult(reply=str(exc), ok=False, error="window_error")
        except Exception as exc:  # noqa: BLE001
            return WindowResult(
                reply="I couldn't control that window.",
                ok=False,
                error=type(exc).__name__,
            )

    def _dispatch(
        self, kind: WindowIntentKind, target: str, snap: str | None
    ) -> WindowResult:
        if kind is WindowIntentKind.MINIMIZE_ALL:
            fn = self._op("minimize_all", minimize_all)
            n = int(fn() or 0)
            return WindowResult(
                reply=f"Minimized {n} windows." if n else "Nothing to minimize.",
                actions=(Action(name="window_minimize_all", detail=str(n)),),
            )

        if kind is WindowIntentKind.FULLSCREEN and not target:
            fs = self._op("fullscreen_media_player", fullscreen_media_player)
            win = fs()
            return WindowResult(
                reply=f"Video fullscreen on {win.process or 'the player'}.",
                actions=(Action(name="window_fullscreen", detail=win.process),),
            )

        if kind is WindowIntentKind.SNAP and not target:
            side = snap or "left"
            sn = self._op("snap_media_player", snap_media_player)
            win = sn(side)
            return WindowResult(
                reply=f"Snapped {win.process or 'the player'} to the {side} half.",
                actions=(Action(name="window_snap", detail=side),),
            )

        win = self._resolve(target)
        if win is None and kind is WindowIntentKind.SNAP:
            # Bare-ish snap with unresolved target → try media player
            side = snap or "left"
            sn = self._op("snap_media_player", snap_media_player)
            win = sn(side)
            return WindowResult(
                reply=f"Snapped {win.process or 'the player'} to the {side} half.",
                actions=(Action(name="window_snap", detail=side),),
            )

        if win is None:
            label = target or "that window"
            return WindowResult(
                reply=f"I couldn't find a window for {label}.",
                ok=False,
                error="not_found",
            )

        if kind is WindowIntentKind.FULLSCREEN:
            if win.process == "vlc":
                fs = self._op("fullscreen_media_player", fullscreen_media_player)
                win = fs(prefer=(win.process,))
            else:
                # Non-VLC: F11-style via fullscreen_media_player prefer this process
                fs = self._op("fullscreen_media_player", fullscreen_media_player)
                try:
                    win = fs(prefer=(win.process,))
                except Exception:
                    self._op("maximize", maximize)(win.hwnd)
            return WindowResult(
                reply=f"Video fullscreen on {win.title or win.process}.",
                actions=(Action(name="window_fullscreen", detail=win.process),),
            )

        if kind is WindowIntentKind.SNAP:
            side = snap or "left"
            self._op("snap_half", snap_half)(win.hwnd, side)
            return WindowResult(
                reply=f"Snapped {win.title or win.process} to the {side} half.",
                actions=(Action(name="window_snap", detail=side),),
            )

        if kind is WindowIntentKind.MAXIMIZE:
            self._op("maximize", maximize)(win.hwnd)
            return WindowResult(
                reply=f"Maximized {win.title or win.process}.",
                actions=(Action(name="window_maximize", detail=win.process),),
            )
        if kind is WindowIntentKind.MINIMIZE:
            self._op("minimize", minimize)(win.hwnd)
            return WindowResult(
                reply=f"Minimized {win.title or win.process}.",
                actions=(Action(name="window_minimize", detail=win.process),),
            )
        if kind is WindowIntentKind.FOCUS:
            self._op("focus", focus)(win.hwnd)
            return WindowResult(
                reply=f"Focused {win.title or win.process}.",
                actions=(Action(name="window_focus", detail=win.process),),
            )
        if kind is WindowIntentKind.CLOSE:
            self._op("close", close)(win.hwnd)
            return WindowResult(
                reply=f"Closed {win.title or win.process}.",
                actions=(Action(name="window_close", detail=win.process),),
            )
        if kind is WindowIntentKind.RESTORE:
            self._op("restore", restore)(win.hwnd)
            return WindowResult(
                reply=f"Restored {win.title or win.process}.",
                actions=(Action(name="window_restore", detail=win.process),),
            )
        return WindowResult(reply="I'm not sure how to manage that window.", ok=False)

    def _resolve(self, target: str) -> WindowInfo | None:
        t = (target or "").strip().lower()
        if not t:
            return None
        find = self._op("find_windows", find_windows)
        wait = self._op("wait_for_window", wait_for_window)

        for alias, procs in _ALIASES.items():
            if alias in t or t in alias:
                for proc in procs:
                    hits = find(process=proc)
                    if hits:
                        return hits[0]
                w = wait(process=procs[0], timeout_s=1.5)
                if w:
                    return w

        hits = find(title_substr=t)
        if hits:
            return hits[0]
        hits = find(process=t)
        if hits:
            return hits[0]
        return wait(title_substr=t, timeout_s=1.5)


def build_window_handler() -> WindowHandler:
    return WindowHandler()
