"""Scriptable fake brain for automated tests — no network, no cost."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from jarvis.types import Action, BrainTurn

TurnFactory = Callable[[str, list[str]], BrainTurn]


@dataclass
class FakeBrain:
    """In-memory brain with optional scripted turns and simple context memory.

    If ``script`` is provided, each ``ask`` consumes the next scripted turn
    (or calls a factory with the command + history). Otherwise uses a small
    rule-based memory so persistence tests can assert on prior context.
    """

    script: Sequence[BrainTurn | TurnFactory] | None = None
    _history: list[str] = field(default_factory=list, init=False)
    _script_i: int = field(default=0, init=False)
    _session_id: str = field(default="fake-session-1", init=False)
    _memory: dict[str, str] = field(default_factory=dict, init=False)
    _last_action_target: str | None = field(default=None, init=False)

    def ask(self, command: str) -> BrainTurn:
        cmd = command.strip()
        self._history.append(cmd)

        if self.script is not None:
            return self._from_script(cmd)

        return self._rule_based(cmd)

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
                ok=turn.ok,
                error=turn.error,
            )
        return turn

    def _rule_based(self, cmd: str) -> BrainTurn:
        lower = cmd.lower()

        # Risky tiers: never auto-run in the fake (mirrors denied-not-prompted).
        if any(
            k in lower
            for k in (
                "delete ",
                "rm -rf",
                "format ",
                "shutdown",
                "send email",
                "send a message",
                "password",
                "api key",
                "secret",
            )
        ):
            return BrainTurn(
                reply="I can't do that automatically — it needs your go-ahead first.",
                actions=(),
                session_id=self._session_id,
                denied=True,
                ok=True,
            )

        if lower.startswith("remember that ") or lower.startswith("remember "):
            fact = cmd.split(" ", 1)[1]
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
            target = cmd.split(" ", 1)[1]
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
            path = cmd.split(" ", 2)[-1]
            return BrainTurn(
                reply=f"Created {path}.",
                actions=(Action(name="write_file", detail=path),),
                session_id=self._session_id,
            )

        return BrainTurn(
            reply=f"Done: {cmd}",
            actions=(),
            session_id=self._session_id,
        )
