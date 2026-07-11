"""Scriptable fake brain for automated tests — no network, no cost."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from jarvis.confirm import (
    confirmation_prompt,
    describe_risky_action,
    is_risky_request,
    is_secret_request,
    sanitize_user_command,
)
from jarvis.types import Action, BrainTurn

TurnFactory = Callable[[str, list[str]], BrainTurn]


@dataclass
class FakeBrain:
    """In-memory brain with optional scripted turns and simple context memory.

    If ``script`` is provided, each ``ask`` consumes the next scripted turn
    (or calls a factory with the command + history). Otherwise uses a small
    rule-based memory so persistence tests can assert on prior context.

    ``delay_s`` sleeps inside ``ask`` (in small slices) so long-task tests can
    background work and exercise ``cancel()``.

    Ask-first (issue 06): risky commands return ``needs_confirmation`` with a
    proposed action and no executed actions. Core re-asks with
    ``confirmed=True`` after an explicit user yes. A user-typed ``CONFIRMED:``
    prefix is stripped and ignored (not authorized). Secrets stay hard-denied.
    """

    script: Sequence[BrainTurn | TurnFactory] | None = None
    delay_s: float = 0.0
    _history: list[str] = field(default_factory=list, init=False)
    _script_i: int = field(default=0, init=False)
    _session_id: str = field(default="fake-session-1", init=False)
    _memory: dict[str, str] = field(default_factory=dict, init=False)
    _last_action_target: str | None = field(default=None, init=False)
    _cancel: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _in_ask: bool = field(default=False, init=False, repr=False)

    def cancel(self) -> None:
        """Abort an in-flight ``ask`` (long-task cancel path)."""
        self._cancel.set()

    def ask(self, command: str, *, confirmed: bool = False) -> BrainTurn:
        # Strip spoof prefixes; only the confirmed= flag authorizes risk.
        cmd = sanitize_user_command(command)
        self._history.append(cmd)
        self._in_ask = True
        try:
            # Honor cancel set before we entered (do not clear at entry — that
            # would drop an early cancel that raced the worker start).
            if self._cancel.is_set():
                return BrainTurn(
                    reply="Cancelled.",
                    actions=(),
                    session_id=self._session_id,
                    ok=False,
                    error="cancelled",
                )
            if self.delay_s > 0:
                cancelled = self._sleep_interruptible(self.delay_s)
                if cancelled:
                    return BrainTurn(
                        reply="Cancelled.",
                        actions=(),
                        session_id=self._session_id,
                        ok=False,
                        error="cancelled",
                    )

            if self.script is not None:
                return self._from_script(cmd)

            return self._rule_based(cmd, confirmed=confirmed)
        finally:
            self._in_ask = False
            # Clear for the next turn only after this ask fully exits.
            self._cancel.clear()

    def _sleep_interruptible(self, seconds: float) -> bool:
        """Sleep up to *seconds*; return True if cancel was requested."""
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            if self._cancel.is_set():
                return True
            remaining = deadline - time.monotonic()
            time.sleep(min(0.05, max(0.0, remaining)))
        return self._cancel.is_set()

    def reset_session(self) -> None:
        """Start a fresh conversation (drop history and script cursor)."""
        self._history.clear()
        self._memory.clear()
        self._last_action_target = None
        self._script_i = 0
        n = self._session_id.rsplit("-", 1)[-1]
        try:
            next_n = int(n) + 1
        except ValueError:
            next_n = 2
        self._session_id = f"fake-session-{next_n}"

    def _from_script(self, cmd: str) -> BrainTurn:
        if self._script_i >= len(self.script):
            raise IndexError(
                f"FakeBrain script exhausted after {len(self.script)} turns; "
                f"got extra command: {cmd!r}"
            )
        item = self.script[self._script_i]
        self._script_i += 1
        if callable(item):
            turn = item(cmd, list(self._history))
        else:
            turn = item
        if turn.session_id is None:
            return BrainTurn(
                reply=turn.reply,
                actions=turn.actions,
                session_id=self._session_id,
                denied=turn.denied,
                needs_confirmation=turn.needs_confirmation,
                proposed_action=turn.proposed_action,
                ok=turn.ok,
                error=turn.error,
            )
        return turn

    def _rule_based(self, cmd: str, *, confirmed: bool = False) -> BrainTurn:
        body = cmd
        lower = body.lower()

        # Secrets: hard-deny at every tier — never confirmation, never execute.
        if is_secret_request(body):
            return BrainTurn(
                reply="I never touch passwords, API keys, or credentials.",
                actions=(),
                session_id=self._session_id,
                denied=True,
                ok=True,
            )

        # Risky: propose only; execute only after core passes confirmed=True.
        if is_risky_request(body):
            if not confirmed:
                proposed = describe_risky_action(body)
                return BrainTurn(
                    reply=confirmation_prompt(proposed),
                    actions=(),
                    session_id=self._session_id,
                    needs_confirmation=True,
                    proposed_action=proposed,
                    ok=True,
                )
            return self._execute_confirmed_risky(body)

        if lower.startswith("remember that ") or lower.startswith("remember "):
            fact = body.split(" ", 1)[1]
            if fact.lower().startswith("that "):
                fact = fact[5:]
            self._memory["last_fact"] = fact
            return BrainTurn(
                reply=f"Got it — I'll remember that {fact}.",
                actions=(Action(name="remember", detail=fact),),
                session_id=self._session_id,
            )

        if "what did i just" in lower or "what is the code" in lower or "what did you remember" in lower:
            fact = self._memory.get("last_fact")
            if fact:
                return BrainTurn(
                    reply=f"You told me: {fact}",
                    actions=(),
                    session_id=self._session_id,
                )
            return BrainTurn(
                reply="I don't have that yet.",
                actions=(),
                session_id=self._session_id,
            )

        if lower.startswith("open ") or lower.startswith("launch "):
            target = body.split(" ", 1)[1]
            self._last_action_target = target
            return BrainTurn(
                reply=f"Opened {target}.",
                actions=(Action(name="launch_app", detail=target),),
                session_id=self._session_id,
            )

        if "actually" in lower and ("close" in lower or "cancel" in lower):
            target = self._last_action_target or "it"
            return BrainTurn(
                reply=f"Closed {target}.",
                actions=(Action(name="close_app", detail=target),),
                session_id=self._session_id,
            )

        if lower.startswith("create file ") or lower.startswith("write file "):
            path = body.split(" ", 2)[-1]
            return BrainTurn(
                reply=f"Created {path}.",
                actions=(Action(name="write_file", detail=path),),
                session_id=self._session_id,
            )

        return BrainTurn(
            reply=f"Done: {body}",
            actions=(),
            session_id=self._session_id,
        )

    def _execute_confirmed_risky(self, body: str) -> BrainTurn:
        """Perform a risky action after the user said yes."""
        lower = body.lower()
        proposed = describe_risky_action(body)

        if "delete" in lower or "rm -rf" in lower or "rm -r" in lower:
            target = proposed.removeprefix("Delete ").strip() or body
            return BrainTurn(
                reply=f"Deleted {target}.",
                actions=(Action(name="delete", detail=target),),
                session_id=self._session_id,
            )

        if "overwrite" in lower:
            target = proposed.removeprefix("Overwrite ").strip() or body
            return BrainTurn(
                reply=f"Overwrote {target}.",
                actions=(Action(name="overwrite", detail=target),),
                session_id=self._session_id,
            )

        if "format" in lower:
            target = proposed.removeprefix("Format ").strip() or body
            return BrainTurn(
                reply=f"Formatted {target}.",
                actions=(Action(name="format", detail=target),),
                session_id=self._session_id,
            )

        if "shutdown" in lower:
            return BrainTurn(
                reply="Shutting down.",
                actions=(Action(name="shutdown", detail=""),),
                session_id=self._session_id,
            )

        if "reboot" in lower:
            return BrainTurn(
                reply="Rebooting.",
                actions=(Action(name="reboot", detail=""),),
                session_id=self._session_id,
            )

        if "send" in lower and "email" in lower:
            return BrainTurn(
                reply="Email sent.",
                actions=(Action(name="send_email", detail=body),),
                session_id=self._session_id,
            )

        if "send" in lower and "message" in lower:
            return BrainTurn(
                reply="Message sent.",
                actions=(Action(name="send_message", detail=body),),
                session_id=self._session_id,
            )

        return BrainTurn(
            reply=f"Done: {body}",
            actions=(Action(name="risky", detail=body),),
            session_id=self._session_id,
        )


__all__ = ["FakeBrain", "TurnFactory"]