"""GrokCliBrain builds the headless Grok CLI invocation shape."""

from __future__ import annotations

from pathlib import Path

from jarvis.brain.grok_cli import GrokCliBrain, parse_grok_output
from jarvis.config import JarvisConfig
from jarvis.types import BrainTurn


def test_build_args_includes_json_approve_and_rules() -> None:
    approved = (Path.home() / "Documents",)
    cfg = JarvisConfig(
        grok_bin="grok",
        grok_model="grok-build",
        approved_folders=approved,
        cwd=Path.cwd(),
    )
    brain = GrokCliBrain(config=cfg)
    args = brain._build_args("open notepad")

    assert args[0] in ("grok",) or "grok" in args[0].lower()
    assert "-p" in args
    assert args[args.index("-p") + 1] == "open notepad"
    assert "--output-format" in args
    assert args[args.index("--output-format") + 1] == "json"
    assert "--always-approve" in args
    # These flags break Grok session create on current CLI — keep them off.
    assert "--tools" not in args
    assert "--disallowed-tools" not in args
    assert "--rules" in args
    prompt = args[args.index("--rules") + 1]
    assert "JARVIS" in prompt
    assert str(approved[0]) in prompt
    assert "--model" in args
    assert args[args.index("--model") + 1] == "grok-build"
    assert "--resume" not in args
    assert "--no-subagents" in args


def test_build_args_resumes_session() -> None:
    brain = GrokCliBrain(config=JarvisConfig(grok_model="grok-build"))
    brain.session_id = "sess-xyz"
    args = brain._build_args("actually close it")
    assert "--resume" in args
    assert args[args.index("--resume") + 1] == "sess-xyz"


def test_reset_session_clears_resume() -> None:
    brain = GrokCliBrain()
    brain.session_id = "sess-1"
    brain.reset_session()
    assert brain.session_id is None
    assert "--resume" not in brain._build_args("hello")


def test_parse_grok_json_output() -> None:
    raw = '{"text":"Opened notepad.","stopReason":"EndTurn","sessionId":"abc-123"}'
    turn = parse_grok_output(raw)
    assert isinstance(turn, BrainTurn)
    assert turn.reply == "Opened notepad."
    assert turn.session_id == "abc-123"
    assert turn.ok


def test_parse_grok_error_object() -> None:
    raw = '{"type":"error","message":"Couldn\'t start session"}'
    turn = parse_grok_output(raw)
    assert not turn.ok
    assert "session" in (turn.reply or "").lower() or turn.error


def test_parse_grok_plain_fallback() -> None:
    turn = parse_grok_output("Done opening the folder.")
    assert turn.reply == "Done opening the folder."
    assert turn.ok


def test_spoken_error_for_session_create_failure() -> None:
    from jarvis.brain.grok_cli import _spoken_error_reply

    msg = (
        "Couldn't create session: Internal error: "
        '"agent building failed: tool error: Requirements unsatisfied"'
    )
    spoken = _spoken_error_reply(msg, msg, "")
    assert "session" in spoken.lower()
    assert len(spoken) < 120
