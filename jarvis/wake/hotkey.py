"""Global push-to-talk hotkey (optional dependency: pynput)."""

from __future__ import annotations

import threading
from typing import Callable


class HotkeyError(RuntimeError):
    """Hotkey backend unavailable or binding failed."""


def parse_hotkey(spec: str) -> str:
    """Normalize a hotkey string for display / pynput.

    Accepts forms like ``ctrl+shift+j``, ``<ctrl>+<shift>+j``.
    Returns a canonical lowercase ``ctrl+shift+j`` style string.
    """
    raw = (spec or "").strip().lower()
    if not raw:
        raise ValueError("hotkey spec is empty")
    # Strip pynput angle brackets if present.
    raw = raw.replace("<", "").replace(">", "")
    parts = [p.strip() for p in raw.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"invalid hotkey spec: {spec!r}")
    aliases = {
        "control": "ctrl",
        "ctl": "ctrl",
        "cmd": "cmd",
        "win": "cmd",
        "windows": "cmd",
        "option": "alt",
        "escape": "esc",
    }
    norm = [aliases.get(p, p) for p in parts]
    return "+".join(norm)


def _pynput_combo(canonical: str) -> str:
    """Convert canonical ``ctrl+shift+j`` to pynput ``<ctrl>+<shift>+j``."""
    parts = canonical.split("+")
    mods = {"ctrl", "alt", "shift", "cmd", "ctrl_l", "ctrl_r", "alt_l", "alt_r"}
    out: list[str] = []
    for p in parts:
        if p in mods or p.endswith("_l") or p.endswith("_r"):
            out.append(f"<{p}>")
        else:
            out.append(p)
    return "+".join(out)


class HotkeyListener:
    """Register a global hotkey; invoke callback on press.

    Safe to construct when pynput is missing — start() raises HotkeyError.
    """

    def __init__(
        self,
        hotkey: str,
        on_press: Callable[[], None],
    ) -> None:
        self.hotkey = parse_hotkey(hotkey)
        self._on_press = on_press
        self._listener = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        try:
            from pynput import keyboard
        except ImportError as exc:
            raise HotkeyError(
                "pynput is required for global hotkeys. "
                'Install with: py -3.13 -m pip install -e ".[wake]"'
            ) from exc

        combo = _pynput_combo(self.hotkey)

        def _wrapped() -> None:
            try:
                self._on_press()
            except Exception:
                pass

        try:
            self._listener = keyboard.GlobalHotKeys({combo: _wrapped})
            self._listener.start()
        except Exception as exc:  # noqa: BLE001
            raise HotkeyError(
                f"Failed to bind hotkey {self.hotkey!r}: {exc}"
            ) from exc
        self._started = True

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        self._started = False

    def __enter__(self) -> HotkeyListener:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


class FakeHotkeyController:
    """Test double: call fire() to simulate the user pressing the hotkey."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.fire_count = 0

    def fire(self) -> None:
        self.fire_count += 1
        self.event.set()

    def clear(self) -> None:
        self.event.clear()
