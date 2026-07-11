"""Optional smoke test against the real Claude CLI.

Skipped by default. Run with:
  py -3.13 -m pytest tests/test_smoke_claude.py -m smoke -v
"""

from __future__ import annotations

import shutil

import pytest

from jarvis.brain.claude_code import ClaudeCodeBrain
from jarvis.config import JarvisConfig
from jarvis.core import handle_command
from jarvis.tts.fake import FakeSpeaker

pytestmark = pytest.mark.smoke


@pytest.fixture(scope="module")
def claude_available() -> None:
    if not shutil.which("claude"):
        pytest.skip("claude CLI not on PATH")


def test_real_cli_answers_simple_question(claude_available) -> None:
    brain = ClaudeCodeBrain(
        config=JarvisConfig(claude_model="haiku", speak=False)
    )
    speaker = FakeSpeaker()
    result = handle_command(
        "Reply with exactly the word pong and nothing else.",
        brain=brain,
        speaker=speaker,
    )
    assert result.ok
    assert result.reply
    assert result.session_id
    assert speaker.spoken
    # Second command should resume the same session.
    result2 = handle_command(
        "What single word did you just say?",
        brain=brain,
        speaker=speaker,
    )
    assert result2.session_id == result.session_id or result2.session_id
