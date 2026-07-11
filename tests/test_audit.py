"""Audit log writes (issue 11)."""

from __future__ import annotations

from pathlib import Path

from jarvis.audit import AuditLog, MemoryAuditLog
from jarvis.brain.fake import FakeBrain
from jarvis.core import handle_command
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import Action, BrainTurn


def test_audit_log_appends_json_lines(tmp_path: Path) -> None:
    path = tmp_path / "audit.log"
    log = AuditLog(path=path, swallow_errors=False)
    log.log("daemon_started", detector="fake")
    log.log("command_received", transcript="open notepad")
    events = log.read_events()
    assert len(events) == 2
    assert events[0]["event"] == "daemon_started"
    assert events[0]["detector"] == "fake"
    assert "ts" in events[0]
    assert events[1]["transcript"] == "open notepad"
    # File is append-only human-readable JSON lines
    text = path.read_text(encoding="utf-8")
    assert text.count("\n") == 2


def test_handle_command_writes_audit() -> None:
    brain = FakeBrain(
        script=[
            BrainTurn(
                reply="Opened Notepad.",
                actions=(Action(name="launch_app", detail="Notepad"),),
            )
        ]
    )
    speaker = FakeSpeaker()
    audit = MemoryAuditLog()
    result = handle_command(
        "open notepad", brain=brain, speaker=speaker, audit=audit
    )
    assert result.ok
    events = [e["event"] for e in audit.events]
    assert "command_received" in events
    assert "command_handled" in events
    handled = next(e for e in audit.events if e["event"] == "command_handled")
    assert handled["reply"] == "Opened Notepad."
    assert handled["actions"][0]["name"] == "launch_app"
    assert handled["path"] == "brain"


def test_memory_audit_is_null_safe() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="Hi.", actions=())])
    speaker = FakeSpeaker()
    # audit=None must not raise
    result = handle_command("hello", brain=brain, speaker=speaker, audit=None)
    assert result.ok


def test_memory_audit_includes_timestamp() -> None:
    audit = MemoryAuditLog()
    audit.log("ping", x=1)
    assert "ts" in audit.events[0]
    assert audit.events[0]["event"] == "ping"


def test_empty_transcript_is_audited() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="unused", actions=())])
    speaker = FakeSpeaker()
    audit = MemoryAuditLog()
    result = handle_command("", brain=brain, speaker=speaker, audit=audit)
    assert result.error == "empty_transcript"
    events = [e["event"] for e in audit.events]
    assert "command_received" in events
    assert "command_handled" in events
