"""Long-running brain tasks: background after ~20s, announce, cancel.

Detection strategy (timeout race)
---------------------------------
``brain.ask`` runs on a worker thread. If it finishes within
``long_task_threshold_s`` (default 20 s), the normal foreground path
speaks the reply immediately. If it is still running past the threshold,
JARVIS speaks a short acknowledgment ("On it."), returns control so the
user is not held at the counter, keeps the overlay in WORKING, and
announces completion or failure when the worker finishes.

Cancel
------
Exact cancel phrases ("cancel", "Jarvis, cancel", …) abort the in-flight
task via ``brain.cancel()`` when available, then speak a confirmation.

Concurrency
-----------
Each start bumps a generation id. The watcher/cancel path may only publish
final state or clear busy when the generation still matches, so a stale
worker cannot corrupt a later task. A new brain turn is refused while the
previous worker thread is still alive (busy or draining).
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from jarvis.brain.base import Brain
from jarvis.confirm import ask_brain
from jarvis.plain_replies import (
    ALREADY_FINISHED,
    BRAIN_EXCEPTION,
    BRAIN_UNREACHABLE,
    CANCELLED,
    NOTHING_TO_CANCEL,
    ON_IT,
    STILL_WORKING,
    looks_like_network_failure,
    plain_error_reply,
)
from jarvis.tts.base import Speaker
from jarvis.types import Action, BrainTurn

if TYPE_CHECKING:
    from jarvis.confirm import Confirmer
    from jarvis.core import CommandResult
    from jarvis.overlay.base import Overlay

# Default: multi-step work in the prototype was ~15–20 s.
DEFAULT_LONG_TASK_THRESHOLD_S = 20.0
DEFAULT_CANCEL_WAIT_S = 5.0
# Extra wait when the worker is already dead but completion TTS is still in flight.
DEFAULT_ANNOUNCE_WAIT_S = 60.0

# Exact cancel phrases only (after wake-phrase strip + lowercasing).
# Deliberately excludes "stop the music", "abort download", etc.
_CANCEL_EXACT: frozenset[str] = frozenset(
    {
        "cancel",
        "stop",
        "abort",
        "never mind",
        "nevermind",
        "cancel that",
        "stop that",
        "abort that",
        "cancel it",
        "stop it",
        "abort it",
        "forget it",
        "please cancel",
        "cancel please",
        "please stop",
        "stop please",
    }
)


def is_cancel_utterance(text: str) -> bool:
    """True when the user is asking to abort the in-flight long task.

    Only exact (or wake-stripped exact) cancel phrases match — not
    "stop the music" / "cancel my meeting" / "dont cancel".
    """
    raw = (text or "").strip().lower()
    if not raw:
        return False
    # Drop trailing/embedded punctuation: "cancel." / "stop!"
    cleaned = re.sub(r"[^\w\s]", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    try:
        from jarvis.wake.phrases import strip_wake_phrase

        stripped = strip_wake_phrase(cleaned)
        if stripped:
            cleaned = stripped.lower().strip()
        elif cleaned:
            # Entire transcript was wake-only — not a cancel.
            return False
    except Exception:  # noqa: BLE001 — cancel detection must stay local
        pass
    return cleaned in _CANCEL_EXACT


def _turn_to_reply(turn: BrainTurn) -> tuple[str, str | None, bool]:
    """Map a BrainTurn to (spoken_reply, error_code, ok) — mirrors core.handle_command."""
    reply = (turn.reply or "").strip()
    error = turn.error
    ok = turn.ok

    if (not turn.ok and looks_like_network_failure(error or reply)) or (
        error == "brain_unreachable"
    ):
        return BRAIN_UNREACHABLE, "brain_unreachable", False
    if error == "cancelled":
        return CANCELLED, "cancelled", False
    if not reply and turn.error:
        reply = plain_error_reply(turn.error, fallback=turn.error)
    elif not reply:
        reply = plain_error_reply(
            turn.error,
            fallback="Done." if turn.ok else None,
        )
    if error == "brain_unreachable":
        ok = False
    return reply, error, ok


def _call_brain(
    brain: Brain, command: str, *, confirmed: bool = False
) -> BrainTurn:
    try:
        return ask_brain(brain, command, confirmed=confirmed)
    except Exception as exc:  # noqa: BLE001 — boundary
        if looks_like_network_failure(exc):
            return BrainTurn(
                reply=BRAIN_UNREACHABLE,
                ok=False,
                error="brain_unreachable",
            )
        return BrainTurn(
            reply=BRAIN_EXCEPTION,
            ok=False,
            error=type(exc).__name__,
        )


def _try_cancel_brain(brain: Brain) -> None:
    cancel_fn = getattr(brain, "cancel", None)
    if callable(cancel_fn):
        try:
            cancel_fn()
        except Exception:  # noqa: BLE001 — best-effort abort
            pass


def _worker_still_alive(thread: threading.Thread | None) -> bool:
    return thread is not None and thread.is_alive()


@dataclass
class LongTaskService:
    """At most one in-flight long brain turn; safe to share across the front door.

    Public surface is intentionally small:
      - ``busy`` / ``wait`` / ``last_final`` for tests and overlay policy
      - ``handle_brain`` for the core loop (timeout race + background + cancel)
    """

    threshold_s: float = DEFAULT_LONG_TASK_THRESHOLD_S
    on_it_text: str = ON_IT
    cancel_wait_s: float = DEFAULT_CANCEL_WAIT_S
    announce_wait_s: float = DEFAULT_ANNOUNCE_WAIT_S
    # Optional auditor for final completion / cancel events (issue 11).
    audit: Any = None

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _watcher: threading.Thread | None = field(default=None, init=False, repr=False)
    _busy: bool = field(default=False, init=False, repr=False)
    _generation: int = field(default=0, init=False, repr=False)
    _cancel_requested: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _done: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _brain: Brain | None = field(default=None, init=False, repr=False)
    _final_result: Any = field(default=None, init=False, repr=False)
    _command: str = field(default="", init=False, repr=False)
    # Completion announce targets (captured when starting / backgrounding).
    _speaker: Speaker | None = field(default=None, init=False, repr=False)
    _overlay: Any = field(default=None, init=False, repr=False)
    _speaking_min_s: float = field(default=0.0, init=False, repr=False)
    _transcript: str = field(default="", init=False, repr=False)

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    @property
    def last_final(self) -> CommandResult | None:
        """Final CommandResult after a backgrounded task finished (tests)."""
        with self._lock:
            return self._final_result

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the in-flight generation fully settles. Returns True if done."""
        return self._done.wait(timeout=timeout)

    def handle_brain(
        self,
        command: str,
        *,
        brain: Brain,
        speaker: Speaker,
        overlay: Overlay | None = None,
        confirmer: Confirmer | None = None,
        speaking_min_s: float = 0.0,
        threshold_s: float | None = None,
        audit: Any = None,
        bus: Any = None,
    ) -> CommandResult:
        """Run brain.ask with timeout-race backgrounding.

        Returns immediately with ``backgrounded=True`` and reply "On it." when
        the turn exceeds the threshold; otherwise behaves like a sync brain turn.

        Ask-first (issue 06): if the foreground turn needs confirmation, run the
        same core gate (never background a confirmation prompt).

        Fault breadth (issue 23): foreground outcomes fault through the core
        seam (the caller audits the returned result); only a BACKGROUNDED
        turn's final failure publishes here, via *bus*, when the watcher
        announces it — same classification, still one Fault per failed turn.
        """
        from jarvis.core import CommandResult, handle_confirmation

        text = (command or "").strip()
        thresh = self.threshold_s if threshold_s is None else threshold_s
        # Prefer call-site audit; fall back to service audit.
        audit_log = audit if audit is not None else self.audit

        # --- cancel path ---
        if is_cancel_utterance(text):
            return self._handle_cancel(
                speaker=speaker, overlay=overlay, speaking_min_s=speaking_min_s
            )

        # --- claim slot atomically (busy + draining worker/watcher) ---
        with self._lock:
            draining = _worker_still_alive(self._thread) or _worker_still_alive(
                self._watcher
            )
            if self._busy or draining:
                # Still-working refusal is returned outside the lock so speak
                # never holds the service lock.
                refuse = True
            else:
                refuse = False
                self._generation += 1
                gen = self._generation
                self._busy = True
                self._cancel_requested.clear()
                self._done.clear()
                self._final_result = None
                self._brain = brain
                self._command = text
                self._speaker = speaker
                self._overlay = overlay
                self._speaking_min_s = speaking_min_s
                self._transcript = text
                self._thread = None  # set after Thread constructed
                self._watcher = None

        if refuse:
            speaker.speak(STILL_WORKING)
            return CommandResult(
                reply=STILL_WORKING,
                actions=(),
                ok=True,
                error="busy",
            )

        box: dict[str, Any] = {}
        started = threading.Event()

        def worker() -> None:
            started.set()
            # First ask is never confirmed — gate happens after if needed.
            box["turn"] = _call_brain(brain, text, confirmed=False)

        thread = threading.Thread(
            target=worker,
            name=f"jarvis-brain-turn-{gen}",
            daemon=True,
        )
        with self._lock:
            if self._generation != gen:
                # Superseded before start (should not happen with single claim).
                return CommandResult(
                    reply=STILL_WORKING,
                    actions=(),
                    ok=True,
                    error="busy",
                )
            self._thread = thread

        thread.start()
        started.wait(timeout=1.0)
        thread.join(timeout=max(0.0, thresh))

        if not thread.is_alive():
            # Finished within threshold — normal foreground completion.
            turn: BrainTurn = box.get(
                "turn",
                BrainTurn(reply=BRAIN_EXCEPTION, ok=False, error="missing_turn"),
            )

            # Ask-first gate (issue 06): never treat a proposal as a final reply.
            # Stay busy through the confirm wait so concurrent turns get
            # STILL_WORKING; only publish final / clear busy when the gate returns.
            if getattr(turn, "needs_confirmation", False) and not turn.denied:
                with self._lock:
                    if self._generation == gen:
                        self._busy = True
                        self._thread = None
                        self._watcher = None
                        # Keep _brain so cancel can still reach it during wait.
                        self._final_result = None
                        # Do not set _done — waiters must block until gate finishes.
                result = handle_confirmation(
                    text,
                    turn,
                    brain=brain,
                    speaker=speaker,
                    overlay=overlay,
                    confirmer=confirmer,
                    audit=audit_log,
                )
                with self._lock:
                    if self._generation == gen:
                        self._busy = False
                        self._brain = None
                        self._final_result = result
                        self._done.set()
                return result

            reply, error, ok = _turn_to_reply(turn)
            if reply:
                speaker.speak(reply)
            result = CommandResult(
                reply=reply,
                actions=tuple(turn.actions),
                session_id=turn.session_id,
                denied=turn.denied,
                ok=ok,
                error=error,
                backgrounded=False,
            )
            with self._lock:
                if self._generation == gen:
                    self._busy = False
                    self._thread = None
                    self._watcher = None
                    self._brain = None
                    self._final_result = result
                    self._done.set()
            return result

        # Still running past threshold → background.
        # Confirmation proposals are local/fast; if we somehow race, the watcher
        # will decline rather than auto-run (see _watch_and_announce).
        speaker.speak(self.on_it_text)
        watcher = threading.Thread(
            target=self._watch_and_announce,
            args=(
                gen,
                thread,
                box,
                speaker,
                overlay,
                speaking_min_s,
                text,
                bus,
            ),
            name=f"jarvis-long-task-watch-{gen}",
            daemon=True,
        )
        with self._lock:
            if self._generation == gen:
                self._watcher = watcher
        watcher.start()
        return CommandResult(
            reply=self.on_it_text,
            actions=(Action(name="task_backgrounded", detail=text),),
            ok=True,
            backgrounded=True,
        )

    def _watch_and_announce(
        self,
        gen: int,
        thread: threading.Thread,
        box: dict[str, Any],
        speaker: Speaker | None,
        overlay: Overlay | None,
        speaking_min_s: float,
        transcript: str,
        bus: Any = None,
    ) -> None:
        from jarvis.core import CommandResult

        thread.join()
        turn: BrainTurn = box.get(
            "turn",
            BrainTurn(reply=BRAIN_EXCEPTION, ok=False, error="missing_turn"),
        )

        with self._lock:
            if self._generation != gen:
                return  # stale generation — do not touch service state
            # Cancel force-path (or another publisher) already finalized.
            if self._final_result is not None:
                self._busy = False
                self._thread = None
                self._watcher = None
                self._brain = None
                self._done.set()
                return
            command = self._command

        # Announce the real turn outcome. Cooperative cancel surfaces as
        # turn.error == "cancelled". A late cancel_requested after the worker
        # already finished must not suppress a success/failure announce —
        # that race is owned by _handle_cancel (wait for watcher, never force).
        cancelled = turn.error == "cancelled"
        if cancelled:
            reply, error, ok = CANCELLED, "cancelled", False
            actions: tuple[Action, ...] = (
                Action(name="task_cancelled", detail=command),
            )
            denied = False
            session_id = turn.session_id
        elif getattr(turn, "needs_confirmation", False) and not turn.denied:
            # Confirmation must never auto-run from a backgrounded path.
            from jarvis.core import CANCELLED_REPLY

            reply, error, ok = CANCELLED_REPLY, "confirmation_declined", True
            actions = ()
            denied = False
            session_id = turn.session_id
        else:
            reply, error, ok = _turn_to_reply(turn)
            actions = tuple(turn.actions)
            denied = turn.denied
            session_id = turn.session_id

        result = CommandResult(
            reply=reply,
            actions=actions,
            session_id=session_id,
            denied=denied,
            ok=ok,
            error=error,
            backgrounded=False,
        )

        # Re-check before speaking: force-cancel (worker still hung) may have published.
        with self._lock:
            if self._generation != gen:
                return
            if self._final_result is not None:
                self._busy = False
                self._thread = None
                self._watcher = None
                self._brain = None
                self._done.set()
                return

        if reply and speaker is not None:
            self._speak_completion(
                speaker,
                reply,
                overlay=overlay,
                speaking_min_s=speaking_min_s,
                transcript=transcript,
            )
        elif overlay is not None:
            try:
                from jarvis.overlay.states import OverlayState

                overlay.set_state(OverlayState.REST, transcript=transcript or None)
            except Exception:  # noqa: BLE001
                pass

        event = "task_cancelled" if cancelled else (
            "task_failed" if not ok else "task_completed"
        )
        self._audit_final(event, result, command=command)
        # Backgrounded final failure faults once here (issue 23) — the "On it."
        # ack the caller audited was ok=True, so the core seam stayed silent.
        # Cancels / declines are excluded by the shared classification.
        from jarvis.core import publish_fault

        publish_fault(bus, result)

        with self._lock:
            if self._generation != gen:
                return
            # If force-cancel published during our speak, keep their result only when
            # it was a true hung-worker force (final already cancelled). Otherwise
            # we own the real turn outcome — but force only runs when worker is
            # alive, so mid-announce force should not happen. Prefer existing final
            # if set; else publish our result.
            if self._final_result is None:
                self._final_result = result
            self._busy = False
            self._thread = None
            self._watcher = None
            self._brain = None
            self._done.set()

    def _speak_completion(
        self,
        speaker: Speaker,
        reply: str,
        *,
        overlay: Overlay | None,
        speaking_min_s: float,
        transcript: str,
    ) -> None:
        try:
            if overlay is not None:
                from jarvis.overlay.lifecycle import SpeakingSpeaker
                from jarvis.overlay.states import OverlayState

                # Avoid double-wrapping when caller already passed SpeakingSpeaker.
                if isinstance(speaker, SpeakingSpeaker):
                    speaker.speak(reply)
                else:
                    SpeakingSpeaker(
                        speaker,
                        overlay,
                        transcript=transcript,
                        speaking_min_s=speaking_min_s,
                    ).speak(reply)
                overlay.set_state(OverlayState.REST, transcript=transcript or None)
            else:
                speaker.speak(reply)
        except Exception:  # noqa: BLE001 — announcement is best-effort
            try:
                speaker.speak(reply)
            except Exception:
                pass

    def _result_from_final(
        self,
        final: CommandResult,
        *,
        command: str,
        speaker: Speaker,
    ) -> CommandResult:
        """Map an already-published final into a cancel-path CommandResult."""
        from jarvis.core import CommandResult

        if final.error == "cancelled":
            return CommandResult(
                reply=CANCELLED,
                actions=(Action(name="task_cancelled", detail=command),),
                ok=False,
                error="cancelled",
            )
        # Success/failure already announced — do not speak Cancelled or rewrite.
        speaker.speak(ALREADY_FINISHED)
        return CommandResult(
            reply=ALREADY_FINISHED,
            actions=(),
            ok=True,
            error="already_finished",
            session_id=final.session_id,
        )

    def _handle_cancel(
        self,
        *,
        speaker: Speaker,
        overlay: Overlay | None = None,
        speaking_min_s: float = 0.0,
    ) -> CommandResult:
        from jarvis.core import CommandResult

        with self._lock:
            busy = (
                self._busy
                or _worker_still_alive(self._thread)
                or _worker_still_alive(self._watcher)
            )
            brain = self._brain
            gen = self._generation
            command = self._command

        if not busy:
            speaker.speak(NOTHING_TO_CANCEL)
            return CommandResult(
                reply=NOTHING_TO_CANCEL,
                actions=(),
                ok=True,
                error=None,
            )

        self._cancel_requested.set()
        if brain is not None:
            _try_cancel_brain(brain)

        # Wait briefly for cooperative cancel / quick finish.
        self._done.wait(timeout=self.cancel_wait_s)

        with self._lock:
            if self._generation != gen:
                return CommandResult(
                    reply=CANCELLED,
                    actions=(Action(name="task_cancelled", detail=command),),
                    ok=False,
                    error="cancelled",
                )
            final = self._final_result
            thread = self._thread
            watcher = self._watcher
            worker_alive = _worker_still_alive(thread)

        if final is not None:
            return self._result_from_final(final, command=command, speaker=speaker)

        # Worker already finished: completion announce is in flight (or about to
        # start). That is NOT a hung task — wait for the watcher, never force
        # Cancelled. (Force-while-worker-dead caused Cancelled. then SUCCESS.)
        if not worker_alive:
            if watcher is not None and watcher.is_alive():
                watcher.join(timeout=self.announce_wait_s)
            else:
                self._done.wait(timeout=self.announce_wait_s)

            with self._lock:
                if self._generation != gen:
                    return CommandResult(
                        reply=CANCELLED,
                        actions=(Action(name="task_cancelled", detail=command),),
                        ok=False,
                        error="cancelled",
                    )
                final = self._final_result

            if final is not None:
                return self._result_from_final(final, command=command, speaker=speaker)

            # Watcher never published (should be rare). Stay busy-safe: do not
            # force-cancel a dead worker; report already-finished neutrally.
            speaker.speak(ALREADY_FINISHED)
            return CommandResult(
                reply=ALREADY_FINISHED,
                actions=(),
                ok=True,
                error="already_finished",
            )

        # Worker still alive after cancel_wait_s → true hung / no-op cancel.
        # Announce Cancelled once; keep busy until the worker dies so a stale
        # watcher cannot be followed by a new task.
        force = CommandResult(
            reply=CANCELLED,
            actions=(Action(name="task_cancelled", detail=command),),
            ok=False,
            error="cancelled",
        )
        with self._lock:
            if self._generation != gen:
                return force
            if self._final_result is None:
                self._final_result = force
            # Worker is alive — leave busy=True; watcher clears when it exits
            # without re-speaking (final already set).

        self._speak_completion(
            speaker,
            CANCELLED,
            overlay=overlay,
            speaking_min_s=speaking_min_s,
            transcript=command,
        )
        self._audit_final("task_cancelled", force, command=command)
        return force

    def _audit_final(self, event: str, result: Any, *, command: str) -> None:
        if self.audit is None:
            return
        try:
            actions = [
                {"name": a.name, "detail": a.detail}
                for a in (getattr(result, "actions", ()) or ())
            ]
            self.audit.log(
                event,
                command=command,
                reply=getattr(result, "reply", None),
                ok=getattr(result, "ok", None),
                error=getattr(result, "error", None),
                actions=actions,
            )
        except Exception:  # noqa: BLE001 — audit must never break announce
            pass
