"""Behavioral tests for markdown long-term memory (issue 07).

Seams:
  - handle_command(transcript, memory=...) → reply + actions + spoken
  - Notes are plain markdown files under the store root (human-editable)
  - A fresh handler on the same root (a "later session") retrieves stored facts
  - Brain _build_args carries a memory digest so the cloud brain can use facts
"""

from __future__ import annotations

from pathlib import Path

from jarvis.brain.fake import FakeBrain
from jarvis.core import handle_command
from jarvis.memory.handler import build_memory_handler
from jarvis.memory.store import MemoryStore
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import Action, BrainTurn


def _memory(tmp_path: Path):
    return build_memory_handler(tmp_path / "memory")


class OfflineConnectivity:
    def is_online(self) -> bool:
        return False


def test_remember_writes_dated_tagged_markdown_note(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    brain = FakeBrain(script=[])  # brain must not be consulted
    speaker = FakeSpeaker()

    result = handle_command(
        "remember that the wifi network is called skynet",
        brain=brain,
        speaker=speaker,
        memory=memory,
    )

    assert result.ok is True
    assert "remember" in result.reply.lower()
    assert "skynet" in result.reply.lower()
    assert any(a.name == "remember" for a in result.actions)
    assert speaker.spoken == [result.reply]
    assert brain._history == []

    notes = list((tmp_path / "memory").glob("*.md"))
    assert len(notes) == 1
    text = notes[0].read_text(encoding="utf-8")
    assert "the wifi network is called skynet" in text
    assert "- Date: " in text
    assert "- Tags: " in text
    assert text.startswith("# ")  # summary heading stays readable


def test_fact_survives_restart_into_a_new_session(tmp_path: Path) -> None:
    """Store in session one, retrieve with a brand-new handler + brain."""
    speaker1 = FakeSpeaker()
    handle_command(
        "remember that my dentist is Dr. Rao",
        brain=FakeBrain(script=[]),
        speaker=speaker1,
        memory=_memory(tmp_path),
    )

    # "Restart": fresh handler over the same folder, fresh brain, fresh speaker.
    speaker2 = FakeSpeaker()
    result = handle_command(
        "what do you remember about my dentist?",
        brain=FakeBrain(script=[]),
        speaker=speaker2,
        memory=_memory(tmp_path),
    )

    assert result.ok is True
    assert "rao" in result.reply.lower()
    assert any(a.name == "recall" for a in result.actions)
    assert speaker2.spoken == [result.reply]


def test_recall_picks_the_right_note_among_many(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    speaker = FakeSpeaker()
    for fact in (
        "remember that the wifi network is called skynet",
        "remember that my dentist is Dr. Rao",
        "remember that the parking spot is number 42",
    ):
        handle_command(fact, brain=FakeBrain(script=[]), speaker=speaker, memory=memory)

    result = handle_command(
        "what did I tell you about the parking spot?",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        memory=memory,
    )

    assert "42" in result.reply
    assert "skynet" not in result.reply.lower()


def test_recall_unknown_fact_says_so_plainly(tmp_path: Path) -> None:
    result = handle_command(
        "what do you remember about my car?",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        memory=_memory(tmp_path),
    )

    assert result.ok is True
    assert "don't have" in result.reply.lower()


def test_recall_all_lists_note_summaries(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    speaker = FakeSpeaker()
    handle_command(
        "remember that the wifi network is called skynet",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        memory=memory,
    )
    handle_command(
        "remember that my dentist is Dr. Rao",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        memory=memory,
    )

    result = handle_command(
        "what do you remember?",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        memory=memory,
    )

    assert "2" in result.reply
    assert "skynet" in result.reply.lower()
    assert "rao" in result.reply.lower()


def test_secrets_are_never_written_to_memory_notes(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    speaker = FakeSpeaker()

    for cmd in (
        "remember that my password is hunter2",
        "remember that my api key is sk-12345",
    ):
        result = handle_command(
            cmd,
            brain=FakeBrain(script=[]),
            speaker=speaker,
            memory=memory,
        )
        assert result.denied is True, cmd
        assert result.actions == ()

    root = tmp_path / "memory"
    files = list(root.rglob("*")) if root.exists() else []
    assert [p for p in files if p.is_file()] == []
    assert speaker.spoken  # refusal is spoken, never silent


def test_forget_removes_the_note_file(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    speaker = FakeSpeaker()
    handle_command(
        "remember that the wifi network is called skynet",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        memory=memory,
    )

    result = handle_command(
        "forget about the wifi network",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        memory=memory,
    )

    assert result.ok is True
    assert "forgotten" in result.reply.lower()
    assert any(a.name == "forget" for a in result.actions)
    assert list((tmp_path / "memory").glob("*.md")) == []

    after = handle_command(
        "what do you remember about the wifi network?",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        memory=memory,
    )
    assert "don't have" in after.reply.lower()


def test_hand_edited_markdown_note_is_retrieved(tmp_path: Path) -> None:
    """The user can write/edit notes by hand — memory is never a black box."""
    root = tmp_path / "memory"
    root.mkdir(parents=True)
    (root / "my-own-note.md").write_text(
        "# Favourite editor\n\nMy favourite editor is Vim.\n",
        encoding="utf-8",
    )

    result = handle_command(
        "what do you remember about my favourite editor?",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        memory=build_memory_handler(root),
    )

    assert "vim" in result.reply.lower()


def test_unrelated_commands_fall_through_to_brain(tmp_path: Path) -> None:
    brain = FakeBrain(
        script=[
            BrainTurn(
                reply="Opened Notepad.",
                actions=(Action(name="launch_app", detail="Notepad"),),
            )
        ]
    )
    speaker = FakeSpeaker()

    result = handle_command(
        "open notepad",
        brain=brain,
        speaker=speaker,
        memory=_memory(tmp_path),
    )

    assert result.reply == "Opened Notepad."
    assert result.actions[0].name == "launch_app"
    assert speaker.spoken == ["Opened Notepad."]


def test_memory_answers_even_when_offline(tmp_path: Path) -> None:
    """Local notes need no network — recall works while the brain is unreachable."""
    memory = _memory(tmp_path)
    speaker = FakeSpeaker()
    handle_command(
        "remember that the code is blue",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        memory=memory,
        connectivity=OfflineConnectivity(),
    )

    result = handle_command(
        "what do you remember about the code?",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        memory=memory,
        connectivity=OfflineConnectivity(),
    )

    assert result.ok is True
    assert "blue" in result.reply.lower()


def test_brain_system_prompts_carry_memory_digest(tmp_path: Path) -> None:
    """Later cloud-brain sessions see remembered facts without being retold."""
    from jarvis.brain.claude_code import ClaudeCodeBrain
    from jarvis.brain.grok_cli import GrokCliBrain
    from jarvis.config import JarvisConfig

    store = MemoryStore(tmp_path / "memory")
    store.remember("the project codename is aurora")
    cfg = JarvisConfig(memory_dir=tmp_path / "memory")

    grok_args = GrokCliBrain(config=cfg)._build_args("hello")
    grok_prompt = grok_args[grok_args.index("--rules") + 1]
    assert "aurora" in grok_prompt
    assert "credential" in grok_prompt.lower()  # never write secrets to notes

    claude_args = ClaudeCodeBrain(config=cfg)._build_args("hello")
    claude_prompt = claude_args[claude_args.index("--append-system-prompt") + 1]
    assert "aurora" in claude_prompt


def test_empty_memory_leaves_brain_prompt_clean(tmp_path: Path) -> None:
    from jarvis.brain.grok_cli import GrokCliBrain
    from jarvis.config import JarvisConfig

    cfg = JarvisConfig(memory_dir=tmp_path / "empty-memory")
    args = GrokCliBrain(config=cfg)._build_args("hello")
    prompt = args[args.index("--rules") + 1]
    assert "Long-term memory" not in prompt


def test_cli_once_remember_then_recall_across_processes(capsys) -> None:
    """CLI wiring: --once stores under the isolated JARVIS_HOME, second run recalls."""
    from jarvis.cli import main

    code = main(
        ["--fake", "--no-speak", "--once", "remember that the code is blue"]
    )
    assert code == 0

    code = main(
        ["--fake", "--no-speak", "--once", "what do you remember about the code?"]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "blue" in captured.out.lower()
