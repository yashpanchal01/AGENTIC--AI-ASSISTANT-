"""Resident lifecycle: pause / resume / quit for the always-on daemon (issue 11).

Pause makes the front door verifiably deaf — wake word and hotkey triggers are
discarded until resume. Quit stops the process cleanly.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

ResidentState = Literal["running", "paused", "stopping"]


@dataclass
class ResidentController:
    """Thread-safe pause/resume/quit controller shared by session + tray.

    *on_state_change* is invoked after every transition (may run on any thread;
    tray glue should marshal to the UI thread).
    """

    audit: Any = None
    on_state_change: Callable[[ResidentState], None] | None = None
    _paused: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    @property
    def is_stopping(self) -> bool:
        return self._stop.is_set()

    @property
    def state(self) -> ResidentState:
        if self._stop.is_set():
            return "stopping"
        if self._paused.is_set():
            return "paused"
        return "running"

    def pause(self) -> None:
        with self._lock:
            if self._stop.is_set():
                return
            already = self._paused.is_set()
            self._paused.set()
        if not already:
            self._emit("pause")
            self._notify()

    def resume(self) -> None:
        with self._lock:
            if self._stop.is_set():
                return
            was_paused = self._paused.is_set()
            self._paused.clear()
        if was_paused:
            self._emit("resume")
            self._notify()

    def quit(self) -> None:
        with self._lock:
            already = self._stop.is_set()
            self._stop.set()
            self._paused.clear()  # unblock any pause waiters
        if not already:
            self._emit("quit")
            self._notify()

    def wait_while_paused(self, *, poll_s: float = 0.1) -> bool:
        """Block while paused. Returns False if stop was requested, True if running."""
        while self._paused.is_set() and not self._stop.is_set():
            self._stop.wait(timeout=poll_s)
        return not self._stop.is_set()

    def _emit(self, event: str) -> None:
        if self.audit is not None:
            try:
                self.audit.log(event, source="resident")
            except Exception:
                pass

    def _notify(self) -> None:
        if self.on_state_change is not None:
            try:
                self.on_state_change(self.state)
            except Exception:
                pass
