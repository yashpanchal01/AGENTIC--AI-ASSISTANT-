"""Headless core loop: transcript → brain → reply + actions → speak."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.brain.base import Brain
from jarvis.tts.base import Speaker
from jarvis.types import Action


@dataclass(frozen=True)
class CommandResult:
    """Observable outcome of one handle_command call."""

    reply: str
    actions: tuple[Action, ...]
    session_id: str | None = None
    denied: bool = False
    ok: bool = True
    error: str | None = None


def handle_command(
    transcript_text: str,
    *,
    brain: Brain,
    speaker: Speaker,
) -> CommandResult:
    """Run one command through the brain and speak the reply.

    This is the automated test seam from the PRD: inject a fake Brain and
    assert on reply text + actions taken.
    """
    text = (transcript_text or "").strip()
    if not text:
        return CommandResult(
            reply="I didn't catch that.",
            actions=(),
            ok=False,
            error="empty_transcript",
        )

    try:
        turn = brain.ask(text)
    except Exception as exc:  # noqa: BLE001 — boundary: never crash the REPL
        reply = "Something went wrong talking to my brain."
        return CommandResult(
            reply=reply,
            actions=(),
            ok=False,
            error=type(exc).__name__,
        )

    reply = (turn.reply or "").strip()
    if not reply and turn.error:
        reply = turn.error
    if not reply:
        reply = "Done." if turn.ok else "Something went wrong."

    if reply:
        speaker.speak(reply)

    return CommandResult(
        reply=reply,
        actions=tuple(turn.actions),
        session_id=turn.session_id,
        denied=turn.denied,
        ok=turn.ok,
        error=turn.error,
    )
