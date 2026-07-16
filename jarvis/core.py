"""Headless core loop: transcript → (google | brain) → reply + actions → speak."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from jarvis.brain.base import Brain
from jarvis.compound import is_compound_command
from jarvis.confirm import Confirmer, ask_brain, sanitize_user_command
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
    from jarvis.dialogue import DialogueThread
    from jarvis.overlay.base import Overlay
    from jarvis.tasks import LongTaskService

CANCELLED_REPLY = "Okay, cancelled."
INCOMPLETE_CONFIRM_REPLY = (
    "I still need a clear go-ahead for that action, so I cancelled it."
)


@runtime_checkable
class GoogleHandler(Protocol):
    """Optional Google Workspace seam.

    try_handle returns an object with reply/actions/denied/ok/error fields, or
    None to fall through to the brain.
    """

    def try_handle(self, utterance: str) -> object | None: ...


@runtime_checkable
class MemoryHandler(Protocol):
    """Optional markdown long-term memory seam (issue 07).

    try_handle returns an object with reply/actions/denied/ok/error fields, or
    None to fall through to Google / the brain.
    """

    def try_handle(self, utterance: str) -> object | None: ...


@runtime_checkable
class SpotifyHandler(Protocol):
    """Optional Spotify playback seam (issue 09).

    try_handle returns an object with reply/actions/denied/ok/error fields, or
    None to fall through to the brain.
    """

    def try_handle(self, utterance: str) -> object | None: ...


@runtime_checkable
class LocalMediaHandler(Protocol):
    """Optional local media seam: find a file on disk and open it for real."""

    def try_handle(self, utterance: str) -> object | None: ...


@runtime_checkable
class WindowHandler(Protocol):
    """Optional Win32 window control (focus / min / max / fullscreen / close)."""

    def try_handle(self, utterance: str) -> object | None: ...


@runtime_checkable
class AppHandler(Protocol):
    """Optional smart app open: focus if running, else launch once."""

    def try_handle(self, utterance: str) -> object | None: ...


@runtime_checkable
class SystemHandler(Protocol):
    """Optional system controls: screen brightness + latest-capture (issue 16)."""

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
    # True when a long brain turn was backgrounded (ack spoken; final later).
    backgrounded: bool = False


def handle_command(
    transcript_text: str,
    *,
    brain: Brain,
    speaker: Speaker,
    google: GoogleHandler | None = None,
    memory: MemoryHandler | None = None,
    spotify: SpotifyHandler | None = None,
    media: LocalMediaHandler | None = None,
    windows: WindowHandler | None = None,
    apps: AppHandler | None = None,
    system: SystemHandler | None = None,
    connectivity: Connectivity | None = None,
    long_tasks: LongTaskService | None = None,
    overlay: Overlay | None = None,
    confirmer: Confirmer | None = None,
    speaking_min_s: float = 0.0,
    long_task_threshold_s: float | None = None,
    audit: Any = None,
    dialogue: DialogueThread | None = None,
) -> CommandResult:
    """Run one command through memory / Google / media / Spotify (if matched) or the brain, then speak.

    Automated test seam (PRD): inject FakeBrain + optional sample_workspace and
    assert on reply text + actions taken.

    Markdown memory (issue 07): when *memory* is provided, "remember that …" /
    "what do you remember …" / "forget …" are answered locally from plain
    markdown notes — before Google and the brain, and even while offline.
    Secrets are never written to memory notes (spoken refusal, ``denied=True``).

    Spotify (issue 09): when *spotify* is provided, everyday music commands —
    play / pause / resume / skip / play by song, artist, or playlist name /
    now-playing / volume — are routed to the Spotify controller before the
    brain. If Spotify isn't configured, the reply is a short spoken pointer to
    docs/spotify-setup.md instead of an error.

    Local media: when *media* is provided, “find X in Downloads and play it” /
    “play the movie X” / ambiguous “play X” that matches a local media file are
    handled by a real OS open (os.startfile) — never delegated to the brain so
    a model cannot claim success without launching the file. Say “fullscreen”
    with the play command to also fullscreen the player after launch.

    Window control: when *windows* is provided, “fullscreen VLC”, “minimize
    chrome”, “focus notepad”, etc. use the Win32 API (not the brain).

    Smart apps: when *apps* is provided, “open brave” focuses an existing
    Brave window if one is running; only launches if nothing is open. Say
    “open a new brave window” to force another instance.

    Compound guard (issue 17): a genuinely multi-step utterance — a conjunction
    followed by a second action verb (“open spotify and play the next music”)
    or a two-window arrangement (“open brave and vs code side by side”) — skips
    every reflex below the memory tier and routes to the brain + MCP tool
    bridge, which composes the whole task instead of a leading reflex
    half-executing the first clause. Single-fact memory notes and everyday
    “play rock and roll” / “open command and conquer” utterances are untouched
    (see :func:`jarvis.compound.is_compound_command`).

    Failures are always spoken in plain language (never silent, never a stack
    trace). When *connectivity* reports offline, the cloud brain is not called
    and JARVIS says its brain is unreachable — local Google reads still work if
    tokens/APIs are available; offline only gates the brain path.

    When *long_tasks* is provided, brain turns that exceed the long-task
    threshold are backgrounded with a spoken "On it." acknowledgment (issue 10).
    Cancel utterances abort the in-flight task. Short/fast turns stay on the
    normal foreground path. Memory and Google handling are always foreground.

    Ask-first (issue 06): when the brain returns ``needs_confirmation``, the
    overlay previews the proposed action and *confirmer* supplies yes/no
    (voice or click). Without a confirmer the safe default is decline — never
    auto-run risky actions. Secrets stay hard-denied (``denied=True``).
    Confirmation proposals are never backgrounded (gate runs in foreground even
    when *long_tasks* is set).

    When *audit* is provided, command receipt, replies, actions, and errors are
    appended to the audit log (issue 11).

    Conversation context (issue 20): when *dialogue* is provided, every tier's
    outcome is appended to the shared :class:`~jarvis.dialogue.DialogueThread`
    (at the audit seam), and brain-bound commands get a terse "recent
    exchanges" digest of the turns the brain has NOT seen (reflex/offline
    turns since its last real turn — ``--resume`` covers its own). After a
    silence longer than the thread's staleness threshold, the thread clears
    and ``brain.reset_session()`` starts a fresh conversation. Reflex-only
    turns never spawn a brain process just to record context.
    """
    text = (transcript_text or "").strip()
    if not text:
        # No command to process — not a failure of an action; stay quiet.
        result = CommandResult(
            reply="I didn't catch that.",
            actions=(),
            ok=False,
            error="empty_transcript",
        )
        _audit(audit, "command_received", transcript="")
        _audit_result(audit, result, path="empty")
        return result

    # Strip spoof CONFIRMED: prefixes from user text (never authorize).
    text = sanitize_user_command(text)
    if not text:
        result = CommandResult(
            reply="I didn't catch that.",
            actions=(),
            ok=False,
            error="empty_transcript",
        )
        _audit(audit, "command_received", transcript="")
        _audit_result(audit, result, path="empty")
        return result

    _audit(audit, "command_received", transcript=text)

    # Staleness reset (issue 20): a long silence means a fresh conversation —
    # clear the dialogue thread AND drop the brain's resume id, like a person
    # walking back into the room. reset_session only clears an id; it never
    # spawns a process, so reflex-only sessions stay brain-free.
    if dialogue is not None and dialogue.reset_if_stale():
        reset = getattr(brain, "reset_session", None)
        if callable(reset):
            try:
                reset()
            except Exception:  # noqa: BLE001 — context hygiene must not break a turn
                pass

    # Brain-bound text carries the digest of turns the brain has not seen
    # (empty on consecutive brain turns — no digest bloat). Computed once here
    # from PRIOR turns; the current turn is appended at the audit seam below.
    brain_text = text
    if dialogue is not None:
        brain_text = dialogue.compose_brain_command(text)

    # Cancel / busy must work even offline and before Google.
    if long_tasks is not None:
        from jarvis.tasks import is_cancel_utterance

        if is_cancel_utterance(text) or long_tasks.busy:
            result = long_tasks.handle_brain(
                text,
                brain=brain,
                speaker=speaker,
                overlay=overlay,
                confirmer=confirmer,
                speaking_min_s=speaking_min_s,
                threshold_s=long_task_threshold_s,
                audit=audit,
            )
            _audit_result(
            audit, result, path="long_task", dialogue=dialogue, utterance=text
        )
            return result

    # Markdown long-term memory (issue 07): local notes answer before Google
    # and the brain, and independently of the network.
    if memory is not None:
        try:
            m_result = memory.try_handle(text)
        except Exception as exc:  # noqa: BLE001 — boundary: never crash the REPL
            reply = "Something went wrong with my memory notes."
            speaker.speak(reply)
            result = CommandResult(
                reply=reply,
                actions=(),
                ok=False,
                error=type(exc).__name__,
            )
            _audit_result(
                audit, result, path="memory", dialogue=dialogue, utterance=text
            )
            return result
        if m_result is not None:
            result = _finish_handler(m_result, speaker=speaker)
            _audit_result(
                audit, result, path="memory", dialogue=dialogue, utterance=text
            )
            return result

    # Compound-command guard (issue 17 gap): a genuinely multi-step utterance
    # ("open spotify and play the next music") must be COMPOSED by the brain +
    # MCP tool bridge, not half-executed by a single leading reflex that grabs
    # the first clause. Placed here — AFTER the memory reflex so single-fact
    # "remember … and …" notes stay local, but BEFORE Google/apps/system/media/
    # windows/spotify so none of those tiers can partially run it. When
    # ``compound`` is True every reflex below is skipped and the command routes
    # to the brain; offline it degrades to BRAIN_UNREACHABLE (never a silent
    # half-execute). The detector is conservative (see jarvis.compound).
    compound = is_compound_command(text)

    offline = connectivity is not None and not connectivity.is_online()

    # Gmail/Calendar before the brain. Live Google needs the network; when
    # offline, refuse reads in plain language (no HTTP hang). Fake sample data
    # sets works_offline=True so demos still answer.
    if google is not None and not compound:
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
                    except Exception as exc:  # noqa: BLE001 — boundary: never crash the REPL
                        reply = "Something went wrong talking to Google."
                        speaker.speak(reply)
                        result = CommandResult(
                            reply=reply,
                            actions=(),
                            ok=False,
                            error=type(exc).__name__,
                        )
                        _audit_result(audit, result, path="google", dialogue=dialogue, utterance=text)
                        return result
                    if g_result is not None:
                        result = _finish_handler(g_result, speaker=speaker)
                        _audit_result(audit, result, path="google", dialogue=dialogue, utterance=text)
                        return result
                else:
                    reply = (
                        "I can't reach Google right now — "
                        "check your internet connection."
                    )
                    speaker.speak(reply)
                    result = CommandResult(
                        reply=reply,
                        actions=(),
                        ok=False,
                        error="google_unreachable",
                    )
                    _audit_result(audit, result, path="google", dialogue=dialogue, utterance=text)
                    return result
        else:
            try:
                g_result = google.try_handle(text)
            except Exception as exc:  # noqa: BLE001 — boundary: never crash the REPL
                reply = "Something went wrong talking to Google."
                speaker.speak(reply)
                result = CommandResult(
                    reply=reply,
                    actions=(),
                    ok=False,
                    error=type(exc).__name__,
                )
                _audit_result(audit, result, path="google", dialogue=dialogue, utterance=text)
                return result
            if g_result is not None:
                result = _finish_handler(g_result, speaker=speaker)
                _audit_result(audit, result, path="google", dialogue=dialogue, utterance=text)
                return result

    # Smart app open before media/brain: focus existing window, else launch once.
    if apps is not None and not compound:
        try:
            a_result = apps.try_handle(text)
        except Exception as exc:  # noqa: BLE001 — boundary
            reply = "Something went wrong opening that app."
            speaker.speak(reply)
            result = CommandResult(
                reply=reply,
                actions=(),
                ok=False,
                error=type(exc).__name__,
            )
            _audit_result(audit, result, path="apps", dialogue=dialogue, utterance=text)
            return result
        if a_result is not None:
            result = _finish_handler(a_result, speaker=speaker)
            _audit_result(audit, result, path="apps", dialogue=dialogue, utterance=text)
            return result

    # System controls (issue 16): screen brightness + "open the last screen
    # recording". Reflex fast path — non-destructive, offline-safe, no brain.
    if system is not None and not compound:
        try:
            sys_result = system.try_handle(text)
        except Exception as exc:  # noqa: BLE001 — boundary: never crash the REPL
            reply = "Something went wrong with that system control."
            speaker.speak(reply)
            result = CommandResult(
                reply=reply,
                actions=(),
                ok=False,
                error=type(exc).__name__,
            )
            _audit_result(audit, result, path="system", dialogue=dialogue, utterance=text)
            return result
        if sys_result is not None:
            result = _finish_handler(sys_result, speaker=speaker)
            _audit_result(audit, result, path="system", dialogue=dialogue, utterance=text)
            return result

    # Local media before Spotify/brain: real disk search + OS open. Offline-safe.
    # Music-shaped utterances return None so Spotify still owns playlists/skip.
    if media is not None and not compound:
        try:
            m_media = media.try_handle(text)
        except Exception as exc:  # noqa: BLE001 — boundary: never crash the REPL
            reply = "Something went wrong opening that media file."
            speaker.speak(reply)
            result = CommandResult(
                reply=reply,
                actions=(),
                ok=False,
                error=type(exc).__name__,
            )
            _audit_result(audit, result, path="media", dialogue=dialogue, utterance=text)
            return result
        if m_media is not None:
            result = _finish_handler(m_media, speaker=speaker)
            _audit_result(audit, result, path="media", dialogue=dialogue, utterance=text)
            return result

    # Win32 window control (focus / min / max / fullscreen / close). Offline-safe.
    if windows is not None and not compound:
        try:
            w_result = windows.try_handle(text)
        except Exception as exc:  # noqa: BLE001 — boundary
            reply = "Something went wrong controlling that window."
            speaker.speak(reply)
            result = CommandResult(
                reply=reply,
                actions=(),
                ok=False,
                error=type(exc).__name__,
            )
            _audit_result(audit, result, path="windows", dialogue=dialogue, utterance=text)
            return result
        if w_result is not None:
            result = _finish_handler(w_result, speaker=speaker)
            _audit_result(audit, result, path="windows", dialogue=dialogue, utterance=text)
            return result

    # Spotify playback before the brain (issue 09). Live control needs the
    # network; setup pointers ("not configured" / "not signed in") are local,
    # so only a signed-in live controller is gated when offline. Fakes set
    # works_offline=True so demos still answer.
    if spotify is not None and not compound:
        works_offline = bool(getattr(spotify, "works_offline", False))
        needs_network = bool(
            getattr(spotify, "configured", True)
            and getattr(spotify, "signed_in", True)
        )
        if offline and not works_offline and needs_network:
            try:
                from jarvis.spotify.intents import SpotifyIntentKind
                from jarvis.spotify.intents import classify as classify_spotify

                s_intent = classify_spotify(text)
            except Exception:
                s_intent = None
            if s_intent is not None and s_intent.kind is not SpotifyIntentKind.UNRELATED:
                reply = (
                    "I can't reach Spotify right now — "
                    "check your internet connection."
                )
                speaker.speak(reply)
                result = CommandResult(
                    reply=reply,
                    actions=(),
                    ok=False,
                    error="spotify_unreachable",
                )
                _audit_result(audit, result, path="spotify", dialogue=dialogue, utterance=text)
                return result
        else:
            try:
                s_result = spotify.try_handle(text)
            except Exception as exc:  # noqa: BLE001 — boundary: never crash the REPL
                reply = "Something went wrong talking to Spotify."
                speaker.speak(reply)
                result = CommandResult(
                    reply=reply,
                    actions=(),
                    ok=False,
                    error=type(exc).__name__,
                )
                _audit_result(audit, result, path="spotify", dialogue=dialogue, utterance=text)
                return result
            if s_result is not None:
                result = _finish_handler(s_result, speaker=speaker)
                _audit_result(audit, result, path="spotify", dialogue=dialogue, utterance=text)
                return result

    if offline:
        reply = BRAIN_UNREACHABLE
        speaker.speak(reply)
        result = CommandResult(
            reply=reply,
            actions=(),
            ok=False,
            error="brain_unreachable",
        )
        _audit_result(audit, result, path="brain", dialogue=dialogue, utterance=text)
        return result

    # Long-task path: timeout race + cancel (issue 10). Confirmation gate runs
    # inside handle_brain for foreground propose turns (never backgrounded).
    if long_tasks is not None:
        result = long_tasks.handle_brain(
            brain_text,
            brain=brain,
            speaker=speaker,
            overlay=overlay,
            confirmer=confirmer,
            speaking_min_s=speaking_min_s,
            threshold_s=long_task_threshold_s,
            audit=audit,
        )
        _audit_result(
            audit, result, path="long_task", dialogue=dialogue, utterance=text
        )
        return result

    try:
        turn = ask_brain(brain, brain_text, confirmed=False)
    except Exception as exc:  # noqa: BLE001 — boundary: never crash the REPL
        if looks_like_network_failure(exc):
            reply = BRAIN_UNREACHABLE
            error = "brain_unreachable"
        else:
            reply = BRAIN_EXCEPTION
            error = type(exc).__name__
        speaker.speak(reply)
        result = CommandResult(
            reply=reply,
            actions=(),
            ok=False,
            error=error,
        )
        _audit_result(audit, result, path="brain", dialogue=dialogue, utterance=text)
        return result

    # Ask-first gate: propose → confirm → re-ask, or cancel (issue 06).
    # The confirmed re-ask keeps brain_text so the digest still reaches the
    # brain (the propose turn was answered locally without spawning it).
    if getattr(turn, "needs_confirmation", False) and not turn.denied:
        result = handle_confirmation(
            brain_text,
            turn,
            brain=brain,
            speaker=speaker,
            overlay=overlay,
            confirmer=confirmer,
            audit=audit,
        )
        _record_dialogue(dialogue, text, result, path="confirm")
        return result

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

    result = CommandResult(
        reply=reply,
        actions=tuple(turn.actions),
        session_id=turn.session_id,
        denied=turn.denied,
        ok=turn.ok if error != "brain_unreachable" else False,
        error=error,
    )
    _audit_result(audit, result, path="brain", dialogue=dialogue, utterance=text)
    return result


def handle_confirmation(
    original_command: str,
    turn: Any,
    *,
    brain: Brain,
    speaker: Speaker,
    overlay: Overlay | None,
    confirmer: Confirmer | None,
    audit: Any = None,
) -> CommandResult:
    """Speak/show the proposed action, wait for yes/no, execute or cancel.

    Public so LongTaskService can share the same gate on foreground turns.
    """
    proposed = (getattr(turn, "proposed_action", None) or "").strip()
    if not proposed:
        proposed = (turn.reply or original_command).strip()
    prompt = (turn.reply or "").strip() or f"{proposed}? Say yes or no."

    if overlay is not None:
        try:
            from jarvis.overlay.states import OverlayState

            overlay.set_state(OverlayState.CONFIRM, transcript=proposed)
            arm = getattr(overlay, "arm_confirm", None)
            if callable(arm):
                arm()
        except Exception:  # noqa: BLE001 — overlay must never break the gate
            pass

    if prompt:
        speaker.speak(prompt)
        # Keep CONFIRM chrome after speak (SpeakingSpeaker may have flipped).
        if overlay is not None:
            try:
                from jarvis.overlay.states import OverlayState

                overlay.set_state(OverlayState.CONFIRM, transcript=proposed)
            except Exception:  # noqa: BLE001
                pass

    confirmed = False
    if confirmer is not None:
        try:
            confirmed = bool(
                confirmer.confirm(prompt=prompt, proposed_action=proposed)
            )
        except Exception:  # noqa: BLE001 — treat confirmer failure as decline
            confirmed = False
    else:
        # No decision channel → safe default is decline (zero auto-run).
        confirmed = False

    if overlay is not None:
        disarm = getattr(overlay, "disarm_confirm", None)
        if callable(disarm):
            try:
                disarm()
            except Exception:  # noqa: BLE001
                pass
        # Leave CONFIRM chrome before follow-up speech (cancel or result).
        # SpeakingSpeaker only preserves CONFIRM while confirm is still armed.
        try:
            from jarvis.overlay.states import OverlayState

            overlay.set_state(OverlayState.WORKING, transcript=proposed)
        except Exception:  # noqa: BLE001
            pass

    if not confirmed:
        reply = CANCELLED_REPLY
        speaker.speak(reply)
        result = CommandResult(
            reply=reply,
            actions=(),
            session_id=getattr(turn, "session_id", None),
            denied=False,
            ok=True,
            error="confirmation_declined",
        )
        _audit_result(audit, result, path="confirm")
        return result

    # User said yes — re-ask with confirmed=True only (never trust text prefix).
    #
    # v1: post-confirm execution is always foreground. We do not re-enter
    # LongTaskService's timeout race here (re-entry would fight the busy slot
    # held during confirm, and propose-gate must stay skipped). A slow Claude
    # confirmed action may block the front door without "On it." backgrounding;
    # elevating that path is a follow-up if needed.
    try:
        turn2 = ask_brain(brain, original_command, confirmed=True)
    except Exception as exc:  # noqa: BLE001 — boundary
        if looks_like_network_failure(exc):
            reply = BRAIN_UNREACHABLE
            error = "brain_unreachable"
        else:
            reply = BRAIN_EXCEPTION
            error = type(exc).__name__
        speaker.speak(reply)
        result = CommandResult(
            reply=reply,
            actions=(),
            ok=False,
            error=error,
        )
        _audit_result(audit, result, path="confirm")
        return result

    # Never allow a second nested confirmation after the user already said yes.
    if getattr(turn2, "needs_confirmation", False) and not turn2.denied:
        reply = INCOMPLETE_CONFIRM_REPLY
        speaker.speak(reply)
        result = CommandResult(
            reply=reply,
            actions=(),
            session_id=turn2.session_id,
            ok=True,
            error="confirmation_incomplete",
        )
        _audit(
            audit,
            "confirmation_incomplete",
            proposed_action=proposed,
            original=original_command,
        )
        _audit_result(audit, result, path="confirm")
        return result

    reply = (turn2.reply or "").strip()
    error = turn2.error
    if (not turn2.ok and looks_like_network_failure(error or reply)) or (
        error == "brain_unreachable"
    ):
        reply = BRAIN_UNREACHABLE
        error = "brain_unreachable"
    elif not reply and turn2.error:
        reply = plain_error_reply(turn2.error, fallback=turn2.error)
    elif not reply:
        reply = plain_error_reply(
            turn2.error,
            fallback="Done." if turn2.ok else None,
        )

    if reply:
        speaker.speak(reply)

    result = CommandResult(
        reply=reply,
        actions=tuple(turn2.actions),
        session_id=turn2.session_id,
        denied=turn2.denied,
        ok=turn2.ok if error != "brain_unreachable" else False,
        error=error,
    )
    _audit_result(audit, result, path="confirm")
    return result


def _audit(audit: Any, event: str, **details: Any) -> None:
    if audit is None:
        return
    try:
        audit.log(event, **details)
    except Exception:
        pass


def _audit_result(
    audit: Any,
    result: CommandResult,
    *,
    path: str,
    dialogue: Any = None,
    utterance: str = "",
) -> None:
    # Dialogue thread (issue 20) shares the audit seam so every tier's outcome
    # is recorded exactly once, without a second scatter of call sites.
    _record_dialogue(dialogue, utterance, result, path=path)
    if audit is None:
        return
    actions = [
        {"name": a.name, "detail": a.detail}
        for a in (result.actions or ())
    ]
    _audit(
        audit,
        "command_handled",
        path=path,
        reply=result.reply,
        ok=result.ok,
        denied=result.denied,
        error=result.error,
        actions=actions,
        session_id=result.session_id,
        backgrounded=result.backgrounded,
    )


# Brain-tier turns that never actually reached a CLI process (local deny /
# declined confirm / unreachable / cancel-control) — the digest must keep
# showing the reflex turns behind them.
_BRAIN_NEVER_SAW = frozenset(
    {
        "brain_unreachable",
        "confirmation_declined",
        "confirmation_incomplete",
        "cancelled",
        "busy",
        "claude_not_found",
        "grok_not_found",
    }
)


def _record_dialogue(
    dialogue: Any, utterance: str, result: CommandResult, *, path: str
) -> None:
    """Append one turn to the shared thread (issue 20). Never breaks a turn."""
    if dialogue is None or path == "empty" or not utterance:
        return
    if path in ("brain", "long_task", "confirm"):
        tier = "offline" if result.error == "brain_unreachable" else "brain"
        seen = (
            tier == "brain"
            and not result.denied
            and result.error not in _BRAIN_NEVER_SAW
        )
    else:
        tier, seen = "reflex", False
    try:
        dialogue.append(
            utterance,
            tier=tier,
            reply=result.reply,
            ok=result.ok,
            seen_by_brain=seen,
        )
    except Exception:  # noqa: BLE001 — working memory is observability, not control
        pass


def _finish_handler(result: object, *, speaker: Speaker) -> CommandResult:
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
