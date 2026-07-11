"""Headless core loop: transcript → (google | brain) → reply + actions → speak."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from jarvis.brain.base import Brain
from jarvis.plain_replies import (
    BRAIN_EXCEPTION,
    BRAIN_UNREACHABLE,
    looks_like_network_failure,
    plain_error_reply,
)
from jarvis.tts.base import Speaker
from jarvis.types import Action

if TYPE_CHECKING:
    from jarvis.connectivity import Connectivity


@runtime_checkable
class GoogleHandler(Protocol):
    """Optional Google Workspace seam.

    try_handle returns an object with reply/actions/denied/ok/error fields, or
    None to fall through to the brain.
    """

    def try_handle(self, utterance: str) -> object | None: ...


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
    google: GoogleHandler | None = None,
    connectivity: Connectivity | None = None,
) -> CommandResult:
    """Run one command through Google (if matched) or the brain, then speak.

    Automated test seam (PRD): inject FakeBrain + optional sample_workspace and
    assert on reply text + actions taken.

    Failures are always spoken in plain language (never silent, never a stack
    trace). When *connectivity* reports offline, the cloud brain is not called
    and JARVIS says its brain is unreachable — local Google reads still work if
    tokens/APIs are available; offline only gates the brain path.
    """
    text = (transcript_text or "").strip()
    if not text:
        # No command to process — not a failure of an action; stay quiet.
        return CommandResult(
            reply="I didn't catch that.",
            actions=(),
            ok=False,
            error="empty_transcript",
        )

    offline = connectivity is not None and not connectivity.is_online()

    # Gmail/Calendar before the brain. Live Google needs the network; when
    # offline, refuse reads in plain language (no HTTP hang). Fake sample data
    # sets works_offline=True so demos still answer.
    if google is not None:
        works_offline = bool(getattr(google, "works_offline", False))
        if offline and not works_offline:
            try:
                from jarvis.google.intents import GoogleIntentKind, classify

                intent = classify(text)
            except Exception:
                intent = None
            if intent is not None and intent.kind is not GoogleIntentKind.UNRELATED:
                write_kinds = (
                    GoogleIntentKind.WRITE_SEND,
                    GoogleIntentKind.WRITE_REPLY,
                    GoogleIntentKind.WRITE_FORWARD,
                    GoogleIntentKind.WRITE_CALENDAR,
                )
                if intent.kind in write_kinds:
                    # Refusals are local — no network.
                    try:
                        g_result = google.try_handle(text)
                    except Exception as exc:  # noqa: BLE001
                        reply = "Something went wrong talking to Google."
                        speaker.speak(reply)
                        return CommandResult(
                            reply=reply,
                            actions=(),
                            ok=False,
                            error=type(exc).__name__,
                        )
                    if g_result is not None:
                        return _finish_google(g_result, speaker=speaker)
                else:
                    reply = (
                        "I can't reach Google right now — "
                        "check your internet connection."
                    )
                    speaker.speak(reply)
                    return CommandResult(
                        reply=reply,
                        actions=(),
                        ok=False,
                        error="google_unreachable",
                    )
        else:
            try:
                g_result = google.try_handle(text)
            except Exception as exc:  # noqa: BLE001 — boundary: never crash the REPL
                reply = "Something went wrong talking to Google."
                speaker.speak(reply)
                return CommandResult(
                    reply=reply,
                    actions=(),
                    ok=False,
                    error=type(exc).__name__,
                )
            if g_result is not None:
                return _finish_google(g_result, speaker=speaker)

    if offline:
        reply = BRAIN_UNREACHABLE
        speaker.speak(reply)
        return CommandResult(
            reply=reply,
            actions=(),
            ok=False,
            error="brain_unreachable",
        )

    try:
        turn = brain.ask(text)
    except Exception as exc:  # noqa: BLE001 — boundary: never crash the REPL
        if looks_like_network_failure(exc):
            reply = BRAIN_UNREACHABLE
            error = "brain_unreachable"
        else:
            reply = BRAIN_EXCEPTION
            error = type(exc).__name__
        speaker.speak(reply)
        return CommandResult(
            reply=reply,
            actions=(),
            ok=False,
            error=error,
        )

    reply = (turn.reply or "").strip()
    error = turn.error

    # Brain may surface network failure as a failed turn rather than an exception.
    if (not turn.ok and looks_like_network_failure(error or reply)) or (
        error == "brain_unreachable"
    ):
        reply = BRAIN_UNREACHABLE
        error = "brain_unreachable"
    elif not reply and turn.error:
        reply = plain_error_reply(turn.error, fallback=turn.error)
    elif not reply:
        reply = plain_error_reply(
            turn.error,
            fallback="Done." if turn.ok else None,
        )

    if reply:
        speaker.speak(reply)

    return CommandResult(
        reply=reply,
        actions=tuple(turn.actions),
        session_id=turn.session_id,
        denied=turn.denied,
        ok=turn.ok if error != "brain_unreachable" else False,
        error=error,
    )


def _finish_google(result: object, *, speaker: Speaker) -> CommandResult:
    reply = (getattr(result, "reply", None) or "").strip()
    error = getattr(result, "error", None)
    ok = bool(getattr(result, "ok", True))
    denied = bool(getattr(result, "denied", False))
    actions = tuple(getattr(result, "actions", ()) or ())
    if not reply and error:
        reply = plain_error_reply(str(error), fallback=str(error))
    if not reply:
        reply = "Done." if ok else "Something went wrong."
    if reply:
        speaker.speak(reply)
    return CommandResult(
        reply=reply,
        actions=actions,
        denied=denied,
        ok=ok,
        error=error,
    )
