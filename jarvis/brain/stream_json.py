"""Parse Claude Code headless stream-json event lines into a BrainTurn.

Kept pure so fixtures from real CLI runs can drive tests without network.

Live step streaming (issue 12): pass ``on_event`` to receive typed
:mod:`jarvis.events` objects (StepStarted / StepFinished / StepFailed /
TokenTick / TaskCompleted) *as each line is ingested* — the Claude brain feeds
lines during the CLI call so subscribers see tool steps while they run, not a
summary afterwards. Without ``on_event`` parsing stays exactly as before.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Iterable

from jarvis.events import (
    Fault,
    StepFailed,
    StepFinished,
    StepStarted,
    TaskCompleted,
    TokenTick,
)
from jarvis.types import Action, BrainTurn


@dataclass
class StreamParseState:
    actions: list[Action] = field(default_factory=list)
    result_text: str = ""
    session_id: str | None = None
    denied: bool = False
    ok: bool = True
    error: str | None = None
    # Optional live observer (issue 12): called once per emitted event.
    on_event: Callable[[object], None] | None = None
    # tool_use id → (name, detail) so tool_result can close the right step.
    _pending_steps: dict[str, tuple[str, str]] = field(default_factory=dict)

    def ingest(self, event: dict[str, Any]) -> None:
        if sid := event.get("session_id"):
            self.session_id = sid

        etype = event.get("type")

        if etype == "assistant":
            message = event.get("message") or {}
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    name = str(block.get("name") or "tool")
                    inp = block.get("input") or {}
                    detail = _tool_detail(name, inp)
                    self.actions.append(
                        Action(name=name, detail=detail, meta={"input": inp})
                    )
                    step_id = block.get("id")
                    step_id = str(step_id) if step_id else None
                    if step_id:
                        self._pending_steps[step_id] = (name, detail)
                    self._emit(
                        StepStarted(name=name, detail=detail, step_id=step_id)
                    )
                elif block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text:
                        self._emit(TokenTick(text=text))

        elif etype == "user":
            message = event.get("message") or {}
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        text = _block_text(block)
                        if _looks_denied(text):
                            self.denied = True
                        step_id = block.get("tool_use_id")
                        step_id = str(step_id) if step_id else None
                        name, detail = self._pending_steps.pop(
                            step_id or "", ("tool", "")
                        )
                        if bool(block.get("is_error")) or _looks_denied(text):
                            self._emit(
                                StepFailed(
                                    name=name,
                                    detail=detail,
                                    step_id=step_id,
                                    error=text[:200],
                                )
                            )
                        else:
                            self._emit(
                                StepFinished(
                                    name=name, detail=detail, step_id=step_id
                                )
                            )

        elif etype == "result":
            subtype = event.get("subtype")
            if subtype and subtype != "success":
                self.ok = False
            result = event.get("result")
            err = event.get("error")
            if isinstance(result, str) and result.strip():
                self.result_text = result.strip()
            elif isinstance(err, str) and err.strip():
                self.error = err.strip()
                self.result_text = self.error
                self.ok = False
            # Only inspect human-facing text fields — not the whole event JSON
            # (which can contain unrelated keys that look like "permission").
            if _looks_denied(self.result_text) or _looks_denied(self.error or ""):
                self.denied = True
            if _looks_rate_limited(self.result_text) or _looks_rate_limited(
                self.error or ""
            ):
                self.ok = False
                self.error = self.error or "rate_limited"
            self._emit(
                TaskCompleted(reply=self.result_text, ok=self.ok, error=self.error)
            )
            # Command/task-level failure boundary (issue 18 wiring): the terminal
            # ``result`` came back not-ok (error subtype, rate limit, or an error
            # field) — the failure counterpart of the green success pulse. Emit a
            # single Fault here, NOT per mid-task StepFailed: a tool step may fail
            # and the turn still recover to ok=True, in which case no Fault fires.
            if not self.ok:
                self._emit(
                    Fault(
                        error=self.error or "task failed",
                        detail=(self.result_text or "")[:200],
                    )
                )

    def _emit(self, event: object) -> None:
        """Hand *event* to the observer; a broken observer never breaks parsing."""
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception:  # noqa: BLE001 — observer isolation
            pass

    def to_turn(self) -> BrainTurn:
        return BrainTurn(
            reply=self.result_text,
            actions=tuple(self.actions),
            session_id=self.session_id,
            denied=self.denied,
            ok=self.ok,
            error=self.error,
        )


def feed_stream_json_line(state: StreamParseState, raw: str) -> None:
    """Ingest one raw stream-json line into *state* (malformed lines skipped).

    This is the live path (issue 12): the Claude brain calls it per line while
    the CLI is still running so ``state.on_event`` fires during the call.
    """
    line = (raw or "").strip()
    if not line:
        return
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return
    if isinstance(event, dict):
        state.ingest(event)


def parse_stream_json_lines(
    lines: Iterable[str],
    *,
    on_event: Callable[[object], None] | None = None,
) -> BrainTurn:
    """Parse newline-delimited stream-json events into a BrainTurn.

    Pass ``on_event`` to observe typed step events per ingested line
    (fixture replays in tests use this to assert exact event sequences).
    """
    state = StreamParseState(on_event=on_event)
    for raw in lines:
        feed_stream_json_line(state, raw)
    return state.to_turn()


def _tool_detail(name: str, inp: dict[str, Any]) -> str:
    for key in ("command", "file_path", "path", "pattern", "url", "query"):
        if key in inp and inp[key] is not None:
            return str(inp[key])
    if inp:
        return json.dumps(inp, default=str)[:200]
    return name


def _block_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    return json.dumps(content or "", default=str)


def _looks_denied(text: str) -> bool:
    return bool(
        text
        and any(
            token in text.lower()
            for token in (
                "permission denied",
                "requires approval",
                "not allowed",
                "permission has been denied",
            )
        )
    )


def _looks_rate_limited(text: str) -> bool:
    lower = (text or "").lower()
    return bool(
        lower
        and any(
            token in lower
            for token in (
                "session limit",
                "rate limit",
                "usage limit",
                "hit your limit",
            )
        )
    )
