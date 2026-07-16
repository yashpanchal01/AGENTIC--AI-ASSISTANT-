"""Conversation context (issue 20): DialogueThread + digest injection.

Quota-safe: brain turns run against FakeBrain or a fake Claude CLI process
(monkeypatched Popen) — never the real CLI. Digest injection is verified via
args-inspection: the command text the brain actually received.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from jarvis.brain.fake import FakeBrain
from jarvis.core import handle_command
from jarvis.dialogue import DIGEST_HEADER, DialogueThread
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import BrainTurn


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _ReflexResult:
    reply: str
    actions: tuple = ()
    denied: bool = False
    ok: bool = True
    error: str | None = None


@dataclass
class _ScriptedReflex:
    """try_handle fake: answers only the utterances in *replies*."""

    replies: dict[str, str]
    works_offline: bool = True
    handled: list[str] = field(default_factory=list)

    def try_handle(self, utterance: str):
        reply = self.replies.get(utterance)
        if reply is None:
            return None
        self.handled.append(utterance)
        return _ReflexResult(reply=reply)


class _Offline:
    def is_online(self) -> bool:
        return False


def _clocked_thread(**kwargs) -> tuple[DialogueThread, dict[str, float]]:
    clock = {"now": 1000.0}
    thread = DialogueThread(now=lambda: clock["now"], **kwargs)
    return thread, clock


# ---------------------------------------------------------------------------
# DialogueThread unit tests
# ---------------------------------------------------------------------------


def test_ring_buffer_turn_9_evicts_turn_1() -> None:
    thread = DialogueThread(max_turns=8)
    for i in range(9):
        thread.append(f"cmd {i}", tier="reflex", reply=f"reply {i}", ok=True)
    assert len(thread.turns) == 8
    assert thread.turns[0].utterance == "cmd 1"
    assert thread.turns[-1].utterance == "cmd 8"


def test_digest_contains_only_unseen_turns() -> None:
    thread = DialogueThread()
    thread.append("open notepad", tier="brain", reply="Opened Notepad.", ok=True)
    thread.append("play dhurandar", tier="reflex", reply="Playing Dhurandar.", ok=True)
    digest = thread.digest()
    assert "play dhurandar" in digest
    assert "open notepad" not in digest  # brain already saw its own turn
    assert digest.startswith(DIGEST_HEADER)


def test_digest_empty_when_brain_is_up_to_date() -> None:
    thread = DialogueThread()
    thread.append("open notepad", tier="brain", reply="Opened Notepad.", ok=True)
    assert thread.digest() == ""
    assert thread.compose_brain_command("close it") == "close it"


def test_digest_marks_failures_and_truncates_long_text() -> None:
    thread = DialogueThread()
    thread.append(
        "play " + "x" * 300,
        tier="reflex",
        reply="y" * 300,
        ok=False,
    )
    digest = thread.digest()
    assert "(failed)" in digest
    # Bounded per line: truncation keeps the digest under a small budget.
    for line in digest.splitlines():
        assert len(line) < 200


def test_digest_stays_under_fixed_budget_at_full_ring() -> None:
    thread = DialogueThread(max_turns=8)
    for i in range(8):
        thread.append("u" * 500, tier="reflex", reply="r" * 500, ok=True)
    assert len(thread.digest()) < 1800  # ~8 capped lines + header/footer


def test_staleness_clears_thread() -> None:
    thread, clock = _clocked_thread(stale_after_s=600.0)
    thread.append("play dhurandar", tier="reflex", reply="Playing.", ok=True)
    clock["now"] += 100.0
    assert thread.reset_if_stale() is False
    assert len(thread.turns) == 1
    clock["now"] += 601.0
    assert thread.reset_if_stale() is True
    assert thread.turns == ()


def test_empty_thread_is_never_stale() -> None:
    thread, clock = _clocked_thread(stale_after_s=1.0)
    clock["now"] += 10_000.0
    assert thread.is_stale() is False
    assert thread.reset_if_stale() is False


# ---------------------------------------------------------------------------
# handle_command integration (FakeBrain args-inspection via _history)
# ---------------------------------------------------------------------------


def test_reflex_then_brain_injects_digest() -> None:
    """"play dhurandar" (reflex) then "pause that thing" (brain) → digest."""
    brain = FakeBrain(script=[BrainTurn(reply="Paused it.")])
    spotify = _ScriptedReflex({"play dhurandar": "Playing Dhurandar on Spotify."})
    speaker = FakeSpeaker()
    dialogue = DialogueThread()

    r1 = handle_command(
        "play dhurandar",
        brain=brain,
        speaker=speaker,
        spotify=spotify,
        dialogue=dialogue,
    )
    assert r1.reply == "Playing Dhurandar on Spotify."
    assert brain._history == []  # reflex-only: brain never consulted

    r2 = handle_command(
        "pause that thing",
        brain=brain,
        speaker=speaker,
        spotify=spotify,
        dialogue=dialogue,
    )
    assert r2.reply == "Paused it."
    assert len(brain._history) == 1
    prompt = brain._history[0]
    assert "play dhurandar" in prompt
    assert "Playing Dhurandar on Spotify." in prompt
    assert prompt.endswith("pause that thing")


def test_consecutive_brain_turns_do_not_reinject() -> None:
    brain = FakeBrain(
        script=[BrainTurn(reply="Opened it."), BrainTurn(reply="Closed it.")]
    )
    speaker = FakeSpeaker()
    dialogue = DialogueThread()

    handle_command("open notepad", brain=brain, speaker=speaker, dialogue=dialogue)
    handle_command("now close it", brain=brain, speaker=speaker, dialogue=dialogue)

    assert brain._history[0] == "open notepad"  # nothing to inject yet
    assert brain._history[1] == "now close it"  # brain saw turn 1 itself
    assert DIGEST_HEADER not in brain._history[1]


def test_stale_gap_resets_thread_and_brain_session() -> None:
    brain = FakeBrain()
    speaker = FakeSpeaker()
    dialogue, clock = _clocked_thread(stale_after_s=600.0)

    r1 = handle_command(
        "open notepad", brain=brain, speaker=speaker, dialogue=dialogue
    )
    sid1 = r1.session_id
    assert sid1 == "fake-session-1"

    clock["now"] += 601.0  # > dialogue_stale_minutes of silence
    r2 = handle_command(
        "open brave", brain=brain, speaker=speaker, dialogue=dialogue
    )
    assert r2.session_id != sid1  # reset_session() → fresh conversation
    assert len(dialogue.turns) == 1  # old thread cleared, new turn only
    assert DIGEST_HEADER not in brain._history[-1]


def test_reflex_only_session_never_touches_brain() -> None:
    brain = FakeBrain(script=[])  # any ask would raise IndexError
    reflex = _ScriptedReflex(
        {"play dhurandar": "Playing.", "pause": "Paused."}
    )
    speaker = FakeSpeaker()
    dialogue = DialogueThread()

    handle_command(
        "play dhurandar", brain=brain, speaker=speaker, spotify=reflex, dialogue=dialogue
    )
    handle_command(
        "pause", brain=brain, speaker=speaker, spotify=reflex, dialogue=dialogue
    )
    assert brain._history == []
    assert [t.tier for t in dialogue.turns] == ["reflex", "reflex"]


def test_all_tiers_append_turns() -> None:
    brain = FakeBrain(script=[BrainTurn(reply="Done it.")])
    reflex = _ScriptedReflex({"play dhurandar": "Playing."})
    speaker = FakeSpeaker()
    dialogue = DialogueThread()

    handle_command(
        "play dhurandar", brain=brain, speaker=speaker, spotify=reflex, dialogue=dialogue
    )
    handle_command(
        "summarize my day",
        brain=brain,
        speaker=speaker,
        spotify=reflex,
        connectivity=_Offline(),
        dialogue=dialogue,
    )
    handle_command(
        "summarize my day", brain=brain, speaker=speaker, spotify=reflex, dialogue=dialogue
    )
    tiers = [t.tier for t in dialogue.turns]
    assert tiers == ["reflex", "offline", "brain"]
    # The offline refusal never reached the brain — it rides the next digest.
    prompt = brain._history[0]
    assert "play dhurandar" in prompt
    assert "(failed)" in prompt  # the offline turn, marked honestly


def test_declined_confirmation_keeps_context_unseen() -> None:
    """A propose→decline never spawns the CLI, so the digest must persist."""
    brain = FakeBrain(script=None)  # rule-based: risky → propose
    reflex = _ScriptedReflex({"play dhurandar": "Playing."})
    speaker = FakeSpeaker()
    dialogue = DialogueThread()

    handle_command(
        "play dhurandar", brain=brain, speaker=speaker, spotify=reflex, dialogue=dialogue
    )
    r = handle_command(
        "delete C:\\temp\\old", brain=brain, speaker=speaker, dialogue=dialogue
    )
    assert r.error == "confirmation_declined"  # no confirmer → safe decline

    digest = dialogue.digest()
    assert "play dhurandar" in digest  # still unseen by a real brain process
    assert "delete" in digest  # the declined exchange itself is context too


def test_memory_reflex_and_compound_gate_unaffected() -> None:
    """Digest rides inside the brain command string only (regression)."""

    class _MemoryReflex(_ScriptedReflex):
        pass

    memory = _MemoryReflex({"remember that the code is blue": "Noted."})
    brain = FakeBrain(script=[BrainTurn(reply="Composed.")])
    speaker = FakeSpeaker()
    dialogue = DialogueThread()

    r1 = handle_command(
        "remember that the code is blue",
        brain=brain,
        speaker=speaker,
        memory=memory,
        dialogue=dialogue,
    )
    assert r1.reply == "Noted."
    # Compound command still routes to the brain (with the digest prepended).
    r2 = handle_command(
        "open brave and play the next music",
        brain=brain,
        speaker=speaker,
        memory=memory,
        dialogue=dialogue,
    )
    assert r2.reply == "Composed."
    assert brain._history[0].startswith(DIGEST_HEADER)
    assert "remember that the code is blue" in brain._history[0]


# ---------------------------------------------------------------------------
# Settings / env wiring
# ---------------------------------------------------------------------------


def test_stale_minutes_settings_key_and_env(monkeypatch) -> None:
    from jarvis.config import JarvisConfig
    from jarvis.settings import apply_user_settings, parse_settings_dict

    settings = parse_settings_dict({"dialogue_stale_minutes": 5})
    assert settings.dialogue_stale_minutes == 5.0
    cfg = apply_user_settings(JarvisConfig(), settings)
    assert cfg.dialogue_stale_minutes == 5.0

    # Invalid / non-positive values fall back to the default (10).
    assert parse_settings_dict({"dialogue_stale_minutes": "x"}).dialogue_stale_minutes is None
    assert parse_settings_dict({"dialogue_stale_minutes": 0}).dialogue_stale_minutes is None

    monkeypatch.setenv("JARVIS_DIALOGUE_STALE_MINUTES", "3")
    assert JarvisConfig.from_env(apply_settings=False).dialogue_stale_minutes == 3.0


# ---------------------------------------------------------------------------
# Fake Claude CLI: argv-level proof the digest reaches the real brain adapter
# ---------------------------------------------------------------------------


class _FakePipe:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)

    def read(self) -> str:
        return ""


class _FakeClaudeProc:
    """Stands in for the Claude CLI: emits one stream-json result line."""

    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.pid = 4321
        self.returncode = 0
        payload = {
            "type": "result",
            "subtype": "success",
            "result": "Paused it.",
            "session_id": "sess-ctx-1",
        }
        self.stdout = _FakePipe([json.dumps(payload) + "\n"])
        self.stderr = _FakePipe([])

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout=None) -> int:
        return self.returncode

    def kill(self) -> None:
        pass


def test_digest_reaches_claude_cli_argv(monkeypatch) -> None:
    from jarvis.brain import claude_code
    from jarvis.config import JarvisConfig

    spawned: list[list[str]] = []

    def _fake_popen(args, **kwargs):
        spawned.append(list(args))
        return _FakeClaudeProc(list(args))

    monkeypatch.setattr(claude_code.subprocess, "Popen", _fake_popen)

    brain = claude_code.ClaudeCodeBrain(config=JarvisConfig())
    reflex = _ScriptedReflex({"play dhurandar": "Playing Dhurandar on Spotify."})
    speaker = FakeSpeaker()
    dialogue = DialogueThread()

    handle_command(
        "play dhurandar", brain=brain, speaker=speaker, spotify=reflex, dialogue=dialogue
    )
    assert spawned == []  # reflex-only turn: no CLI process at all

    handle_command(
        "pause that thing", brain=brain, speaker=speaker, spotify=reflex, dialogue=dialogue
    )
    assert len(spawned) == 1
    args = spawned[0]
    prompt = args[args.index("-p") + 1]
    assert prompt.startswith(DIGEST_HEADER)
    assert '"play dhurandar" -> reflex: "Playing Dhurandar on Spotify." (ok)' in prompt
    assert prompt.endswith("pause that thing")

    # Consecutive brain turn: --resume carries context; no digest bloat.
    handle_command(
        "resume the music", brain=brain, speaker=speaker, spotify=reflex, dialogue=dialogue
    )
    args2 = spawned[1]
    prompt2 = args2[args2.index("-p") + 1]
    assert prompt2 == "resume the music"
    assert "--resume" in args2
    assert args2[args2.index("--resume") + 1] == "sess-ctx-1"
