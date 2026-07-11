"""Behavioral tests for Google Gmail/Calendar read-only (issue 08).

Seams:
  - handle_command(transcript, google=...) → reply + actions + spoken
  - GoogleWorkspace.try_handle for intent routing (tested only via handle_command)
  - TokenStore path is outside the markdown memory directory
"""

from __future__ import annotations

from pathlib import Path

from jarvis.brain.fake import FakeBrain
from jarvis.core import handle_command
from jarvis.google.fake import FakeGmail, sample_workspace
from jarvis.google.tokens import TokenStore, default_token_path, memory_notes_dir
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import Action, BrainTurn


def test_any_new_email_returns_spoken_unread_summary() -> None:
    brain = FakeBrain(script=[])  # brain must not be consulted
    speaker = FakeSpeaker()
    google = sample_workspace()

    result = handle_command(
        "any new email?",
        brain=brain,
        speaker=speaker,
        google=google,
    )

    assert result.ok is True
    assert result.denied is False
    assert "invoice" in result.reply.lower() or "unread" in result.reply.lower()
    assert any(a.name == "gmail_unread" for a in result.actions)
    assert speaker.spoken == [result.reply]
    assert brain._history == []


def test_search_inbox_by_voice() -> None:
    speaker = FakeSpeaker()
    google = sample_workspace()

    result = handle_command(
        "search my inbox for invoices",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        google=google,
    )

    assert result.ok is True
    assert "invoice" in result.reply.lower()
    assert any(a.name == "gmail_search" for a in result.actions)
    assert speaker.spoken == [result.reply]


def test_summarize_named_thread_aloud() -> None:
    speaker = FakeSpeaker()
    google = sample_workspace()

    result = handle_command(
        "summarize the thread about the project kickoff",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        google=google,
    )

    assert result.ok is True
    assert "kickoff" in result.reply.lower() or "project" in result.reply.lower()
    assert any(a.name == "gmail_thread" for a in result.actions)
    assert speaker.spoken


def test_calendar_today_spoken() -> None:
    speaker = FakeSpeaker()
    google = sample_workspace()

    result = handle_command(
        "what's on my calendar today?",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        google=google,
    )

    assert result.ok is True
    assert "standup" in result.reply.lower() or "today" in result.reply.lower()
    assert any(a.name == "calendar_today" for a in result.actions)
    assert speaker.spoken == [result.reply]


def test_next_event_spoken() -> None:
    speaker = FakeSpeaker()
    google = sample_workspace()

    result = handle_command(
        "what's my next event?",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        google=google,
    )

    assert result.ok is True
    assert result.reply
    assert any(a.name == "calendar_next" for a in result.actions)
    assert speaker.spoken


def test_free_at_three_spoken() -> None:
    speaker = FakeSpeaker()
    google = sample_workspace()

    result = handle_command(
        "am I free at three?",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        google=google,
    )

    assert result.ok is True
    assert "free" in result.reply.lower() or "busy" in result.reply.lower()
    assert any(a.name == "calendar_free_at" for a in result.actions)
    assert speaker.spoken


def test_send_email_declined_read_only_reason() -> None:
    speaker = FakeSpeaker()
    google = sample_workspace()

    result = handle_command(
        "send an email to bob saying hello",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        google=google,
    )

    assert result.denied is True
    assert result.actions == ()
    assert "read-only" in result.reply.lower() or "read only" in result.reply.lower()
    assert "send" in result.reply.lower() or "won't" in result.reply.lower()
    assert speaker.spoken == [result.reply]


def test_reply_and_forward_declined() -> None:
    speaker = FakeSpeaker()
    google = sample_workspace()

    for cmd in (
        "reply to that email saying yes",
        "forward the invoice email to accounting",
    ):
        result = handle_command(
            cmd,
            brain=FakeBrain(script=[]),
            speaker=speaker,
            google=google,
        )
        assert result.denied is True, cmd
        assert result.actions == ()
        assert "read" in result.reply.lower()


def test_calendar_write_declined() -> None:
    speaker = FakeSpeaker()
    google = sample_workspace()

    result = handle_command(
        "create a calendar event for tomorrow at noon",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        google=google,
    )

    assert result.denied is True
    assert result.actions == ()
    assert "read" in result.reply.lower()
    assert speaker.spoken


def test_not_signed_in_prompts_login_for_email() -> None:
    speaker = FakeSpeaker()
    google = sample_workspace(signed_in=False)

    result = handle_command(
        "any new email?",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        google=google,
    )

    assert result.ok is False
    assert "sign" in result.reply.lower() or "login" in result.reply.lower()
    assert result.actions == ()
    assert speaker.spoken == [result.reply]


def test_non_google_commands_still_use_brain() -> None:
    from jarvis.types import Action, BrainTurn

    brain = FakeBrain(
        script=[
            BrainTurn(
                reply="Opened Notepad.",
                actions=(Action(name="launch_app", detail="Notepad"),),
            )
        ]
    )
    speaker = FakeSpeaker()
    google = sample_workspace()

    result = handle_command(
        "open notepad",
        brain=brain,
        speaker=speaker,
        google=google,
    )

    assert result.reply == "Opened Notepad."
    assert result.actions[0].name == "launch_app"
    assert speaker.spoken == ["Opened Notepad."]


def test_without_google_arg_brain_handles_as_before() -> None:
    speaker = FakeSpeaker()
    result = handle_command(
        "open notepad",
        brain=FakeBrain(),
        speaker=speaker,
    )
    assert "Opened" in result.reply or "notepad" in result.reply.lower()


def test_token_store_writes_outside_memory_notes(tmp_path: Path) -> None:
    token_path = tmp_path / "secure" / "google_token.json"
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    store = TokenStore(path=token_path, memory_notes_root=memory_dir)

    payload = {"token": "secret-refresh-xyz", "scopes": ["gmail.readonly"]}
    store.save(payload)

    assert token_path.is_file()
    assert store.load() == payload
    # Nothing under memory notes may contain the token material.
    for p in memory_dir.rglob("*"):
        if p.is_file():
            assert "secret-refresh-xyz" not in p.read_text(encoding="utf-8")
    assert not str(token_path).startswith(str(memory_dir))
    assert TokenStore.is_safe_path(token_path, memory_notes_root=memory_dir)


def test_default_token_path_is_not_under_memory_notes() -> None:
    token = default_token_path()
    mem = memory_notes_dir()
    assert TokenStore.is_safe_path(token, memory_notes_root=mem)


def test_spoken_reply_never_includes_raw_token_material() -> None:
    """Spoken summaries must not carry OAuth material."""
    gmail = FakeGmail(unread_text="You have 1 unread from alice.")
    google = sample_workspace(gmail=gmail)
    speaker = FakeSpeaker()
    result = handle_command(
        "any new email?",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        google=google,
    )
    assert "token" not in result.reply.lower()
    assert "refresh" not in result.reply.lower()
    assert "ya29." not in result.reply  # typical Google access-token prefix
