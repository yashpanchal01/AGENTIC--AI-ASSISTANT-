"""Parse Claude Code headless stream-json event lines into a BrainTurn.

Kept pure so fixtures from real CLI runs can drive tests without network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from jarvis.types import Action, BrainTurn


@dataclass
class StreamParseState:
    actions: list[Action] = field(default_factory=list)
    result_text: str = ""
    session_id: str | None = None
    denied: bool = False
    ok: bool = True
    error: str | None = None

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

    def to_turn(self) -> BrainTurn:
        return BrainTurn(
            reply=self.result_text,
            actions=tuple(self.actions),
            session_id=self.session_id,
            denied=self.denied,
            ok=self.ok,
            error=self.error,
        )


def parse_stream_json_lines(lines: Iterable[str]) -> BrainTurn:
    """Parse newline-delimited stream-json events into a BrainTurn."""
    state = StreamParseState()
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            state.ingest(event)
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
