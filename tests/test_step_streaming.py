"""Live step streaming (issue 12): events fire DURING the brain call.

The Claude stream-json parse path emits StepStarted / StepFinished /
TokenTick / TaskCompleted as each line arrives; a scripted fake CLI process
(python script that sleeps between lines) proves subscribers see steps while
the call is still in flight — not summarized after it returns.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from jarvis.brain.claude_code import ClaudeCodeBrain
from jarvis.brain.grok_cli import GrokCliBrain
from jarvis.brain.stream_json import parse_stream_json_lines
from jarvis.config import JarvisConfig
from jarvis.events import (
    EventBus,
    Fault,
    StepFailed,
    StepFinished,
    StepStarted,
    TaskCompleted,
    TokenTick,
)


def _line(obj: dict) -> str:
    return json.dumps(obj)


# -- fixture replay: exact event sequence -------------------------------------


def test_fixture_replay_emits_exact_event_sequence() -> None:
    lines = [
        _line({"type": "system", "session_id": "sess-1"}),
        _line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Let me open that."},
                        {
                            "type": "tool_use",
                            "id": "tu_1",
                            "name": "Bash",
                            "input": {"command": "notepad.exe"},
                        },
                    ]
                },
            }
        ),
        _line(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_1",
                            "content": "ok",
                        }
                    ]
                },
            }
        ),
        _line(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "sess-1",
                "result": "Opened Notepad.",
            }
        ),
    ]

    events: list[object] = []
    turn = parse_stream_json_lines(lines, on_event=events.append)

    assert events == [
        TokenTick(text="Let me open that."),
        StepStarted(name="Bash", detail="notepad.exe", step_id="tu_1"),
        StepFinished(name="Bash", detail="notepad.exe", step_id="tu_1"),
        TaskCompleted(reply="Opened Notepad.", ok=True, error=None),
    ]
    # Parsing result unchanged by observation.
    assert turn.reply == "Opened Notepad."
    assert turn.session_id == "sess-1"
    assert [a.name for a in turn.actions] == ["Bash"]


def test_tool_result_error_emits_step_failed() -> None:
    lines = [
        _line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tu_9",
                            "name": "Write",
                            "input": {"file_path": "C:/locked.txt"},
                        }
                    ]
                },
            }
        ),
        _line(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_9",
                            "is_error": True,
                            "content": "Error: file is locked",
                        }
                    ]
                },
            }
        ),
    ]

    events: list[object] = []
    parse_stream_json_lines(lines, on_event=events.append)

    assert events[0] == StepStarted(
        name="Write", detail="C:/locked.txt", step_id="tu_9"
    )
    failed = events[1]
    assert isinstance(failed, StepFailed)
    assert failed.name == "Write"
    assert failed.step_id == "tu_9"
    assert "locked" in failed.error


def test_failed_result_emits_no_fault_at_parse_level() -> None:
    # A terminal result that came back not-ok still emits TaskCompleted(ok=False),
    # but NO Fault here: fault publication was hoisted from this brain result
    # boundary to the core seam (issue 23) so every tier shares one publisher.
    lines = [
        _line(
            {
                "type": "result",
                "subtype": "error_during_execution",
                "error": "rate limit reached",
            }
        ),
    ]
    events: list[object] = []
    parse_stream_json_lines(lines, on_event=events.append)

    completed = [e for e in events if isinstance(e, TaskCompleted)]
    assert len(completed) == 1 and completed[0].ok is False
    assert not any(isinstance(e, Fault) for e in events)


def test_recovered_step_failure_does_not_emit_fault() -> None:
    # A tool step fails mid-turn, but the turn recovers and the terminal result
    # is success -> StepFailed fires, but NO Fault (no double-firing noise).
    lines = [
        _line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tu_1",
                            "name": "Bash",
                            "input": {"command": "flaky"},
                        }
                    ]
                },
            }
        ),
        _line(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tu_1",
                            "is_error": True,
                            "content": "transient error",
                        }
                    ]
                },
            }
        ),
        _line(
            {"type": "result", "subtype": "success", "result": "Recovered, done."}
        ),
    ]
    events: list[object] = []
    parse_stream_json_lines(lines, on_event=events.append)

    assert any(isinstance(e, StepFailed) for e in events)
    assert any(isinstance(e, TaskCompleted) and e.ok for e in events)
    assert not any(isinstance(e, Fault) for e in events)


def test_parse_without_observer_is_unchanged() -> None:
    lines = [
        _line({"type": "result", "subtype": "success", "result": "Hi."}),
    ]
    turn = parse_stream_json_lines(lines)
    assert turn.reply == "Hi."


# -- live emission: events land while the CLI is still running ----------------

_FAKE_CLAUDE = """\
import json, sys, time

def emit(obj):
    print(json.dumps(obj))
    sys.stdout.flush()

emit({"type": "system", "session_id": "sess-live"})
emit({
    "type": "assistant",
    "message": {"content": [
        {"type": "text", "text": "Working on it."},
        {"type": "tool_use", "id": "tu_1", "name": "Bash",
         "input": {"command": "echo hi"}},
    ]},
})
time.sleep(1.0)
emit({
    "type": "user",
    "message": {"content": [
        {"type": "tool_result", "tool_use_id": "tu_1", "content": "hi"},
    ]},
})
emit({"type": "result", "subtype": "success", "session_id": "sess-live",
      "result": "Done: hi."})
"""


def test_step_events_fire_during_claude_call_not_after(tmp_path: Path) -> None:
    script = tmp_path / "fake_claude_cli.py"
    script.write_text(_FAKE_CLAUDE, encoding="utf-8")

    bus = EventBus()
    timeline: list[tuple[object, float]] = []
    bus.subscribe(lambda e: timeline.append((e, time.monotonic())))

    brain = ClaudeCodeBrain(config=JarvisConfig(), bus=bus)
    # Route the spawn at our scripted CLI (instance attribute shadows the method).
    brain._build_args = lambda body: [sys.executable, "-u", str(script)]  # type: ignore[method-assign]

    turn = brain.ask("say hi")
    returned_at = time.monotonic()

    assert turn.ok
    assert turn.reply == "Done: hi."
    assert turn.session_id == "sess-live"
    assert [a.name for a in turn.actions] == ["Bash"]

    started = [
        (e, ts) for (e, ts) in timeline if isinstance(e, StepStarted)
    ]
    finished = [
        (e, ts) for (e, ts) in timeline if isinstance(e, StepFinished)
    ]
    ticks = [e for (e, _ts) in timeline if isinstance(e, TokenTick)]
    completed = [e for (e, _ts) in timeline if isinstance(e, TaskCompleted)]

    assert [e.name for (e, _ts) in started] == ["Bash"]
    assert [e.name for (e, _ts) in finished] == ["Bash"]
    assert [t.text for t in ticks] == ["Working on it."]
    assert [c.reply for c in completed] == ["Done: hi."]

    # The scripted CLI sleeps 1.0 s AFTER announcing the tool step. If steps
    # were only summarized at the end, StepStarted would land within a few ms
    # of ask() returning — live emission lands it a sleep-width earlier.
    step_started_at = started[0][1]
    assert returned_at - step_started_at >= 0.5, (
        "StepStarted arrived only when ask() returned — not live"
    )
    # And the finish still happens before ask() returns, in order.
    assert step_started_at < finished[0][1] <= returned_at


_FAKE_CLAUDE_FAIL = """\
import json, sys

def emit(obj):
    print(json.dumps(obj))
    sys.stdout.flush()

emit({"type": "system", "session_id": "sess-fail"})
emit({"type": "result", "subtype": "error_during_execution",
      "session_id": "sess-fail", "error": "disk full"})
"""


def test_failed_claude_turn_publishes_exactly_one_fault(tmp_path: Path) -> None:
    """A real (scripted, no-network) failing brain turn through the full
    ``handle_command`` path publishes exactly one Fault — regression for the
    issue 23 hoist (no double-fire from a leftover brain-boundary publisher)."""
    from jarvis.core import handle_command
    from jarvis.tts.fake import FakeSpeaker

    script = tmp_path / "fake_claude_fail.py"
    script.write_text(_FAKE_CLAUDE_FAIL, encoding="utf-8")

    bus = EventBus()
    events: list[object] = []
    bus.subscribe(events.append)

    brain = ClaudeCodeBrain(config=JarvisConfig(), bus=bus)
    brain._build_args = lambda body: [sys.executable, "-u", str(script)]  # type: ignore[method-assign]

    result = handle_command(
        "do the thing", brain=brain, speaker=FakeSpeaker(), bus=bus
    )

    assert result.ok is False
    faults = [e for e in events if isinstance(e, Fault)]
    assert len(faults) == 1
    assert "disk full" in faults[0].error.lower()
    # The failed TaskCompleted still fires; Fault is its counterpart, not a dup.
    completed = [e for e in events if isinstance(e, TaskCompleted)]
    assert len(completed) == 1 and completed[0].ok is False


def test_grok_reports_step_events_per_tool_call(tmp_path: Path) -> None:
    payload = {
        "text": "Opened it.",
        "sessionId": "g-1",
        "toolCalls": [
            {"name": "run_terminal_cmd", "command": "start notepad"},
        ],
    }
    script = tmp_path / "fake_grok_cli.py"
    script.write_text(
        "import json\nprint(json.dumps(" + repr(payload) + "))\n",
        encoding="utf-8",
    )

    bus = EventBus()
    events: list[object] = []
    bus.subscribe(events.append)

    brain = GrokCliBrain(config=JarvisConfig(), bus=bus)
    brain._build_args = lambda body: [sys.executable, "-u", str(script)]  # type: ignore[method-assign]

    turn = brain.ask("open notepad")

    assert turn.ok
    assert turn.reply == "Opened it."
    steps = [e for e in events if isinstance(e, (StepStarted, StepFinished))]
    assert steps == [
        StepStarted(name="run_terminal_cmd", detail="start notepad"),
        StepFinished(name="run_terminal_cmd", detail="start notepad"),
    ]
