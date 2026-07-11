"""Parse real-shaped stream-json fixtures without calling the Claude CLI."""

from __future__ import annotations

import json

from jarvis.brain.stream_json import parse_stream_json_lines


def _line(obj: dict) -> str:
    return json.dumps(obj)


def test_parses_tool_use_and_result() -> None:
    lines = [
        _line({"type": "system", "session_id": "sess-abc"}),
        _line(
            {
                "type": "assistant",
                "session_id": "sess-abc",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "notepad.exe"},
                        }
                    ]
                },
            }
        ),
        _line(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "sess-abc",
                "result": "Opened Notepad.",
            }
        ),
    ]

    turn = parse_stream_json_lines(lines)

    assert turn.session_id == "sess-abc"
    assert turn.reply == "Opened Notepad."
    assert turn.ok is True
    assert len(turn.actions) == 1
    assert turn.actions[0].name == "Bash"
    assert "notepad" in turn.actions[0].detail.lower()


def test_detects_permission_denied_in_tool_result() -> None:
    lines = [
        _line({"type": "system", "session_id": "s1"}),
        _line(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "content": "Error: permission denied by policy",
                        }
                    ]
                },
            }
        ),
        _line(
            {
                "type": "result",
                "subtype": "success",
                "result": "I wasn't allowed to do that.",
            }
        ),
    ]

    turn = parse_stream_json_lines(lines)

    assert turn.denied is True
    assert "allowed" in turn.reply.lower() or turn.reply


def test_ignores_malformed_lines() -> None:
    lines = [
        "not json",
        "",
        _line({"type": "result", "subtype": "success", "result": "Hi."}),
    ]
    turn = parse_stream_json_lines(lines)
    assert turn.reply == "Hi."


def test_error_result_marks_not_ok() -> None:
    lines = [
        _line(
            {
                "type": "result",
                "subtype": "error",
                "error": "network down",
            }
        )
    ]
    turn = parse_stream_json_lines(lines)
    assert turn.ok is False
    assert "network" in (turn.reply or "").lower()


def test_session_limit_marks_not_ok_without_denied() -> None:
    lines = [
        _line(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "s1",
                "result": "You've hit your session limit · resets 10:10pm",
            }
        )
    ]
    turn = parse_stream_json_lines(lines)
    assert turn.ok is False
    assert turn.denied is False
    assert "limit" in turn.reply.lower()
