"""Ask-first confirmation seam (issue 06).

Risky actions never auto-run: the brain proposes a clear action, the core
speaks it and waits for an explicit yes/no via a Confirmer. Secrets never
enter this flow — they stay hard-denied.

Decision policy:
  - yes / affirmative voice or click → proceed (re-ask brain with confirmed=True)
  - no / decline / unclear / timeout / no confirmer → cancel, no actions

Authorization: only ``brain.ask(..., confirmed=True)`` from the core after a
real Confirmer yes. A user-typed ``CONFIRMED:`` prefix is stripped and ignored.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Legacy/spoof prefix that may appear in user text — never authorizes execution.
CONFIRMED_PREFIX = "CONFIRMED:"

# Hard-deny forever — never confirmation, never execute.
_SECRET_TOKENS: tuple[str, ...] = (
    "password",
    "api key",
    "api_key",
    "apikey",
    "credentials",
    "credential",
    "secret key",
    "secrets file",
    "private key",
)

# Ask-first: destructive, system-level, outward-facing (non-Google path).
_RISKY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bdelete\b",
        r"\berase\b",
        r"\bremove\b",
        r"\bwipe\b",
        r"\bunlink\b",
        r"\boverwrite\b",
        r"\brm\s+-rf\b",
        r"\brm\s+-r\b",
        r"\brm\s+",
        r"\bdel\s+",
        r"\bformat\b",
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bsend\s+(an?\s+)?email\b",
        r"\bsend\s+a\s+message\b",
        r"\buninstall\b",
        r"\bregistry\b",
        r"\bregedit\b",
        r"\bnet\s+user\b",
        r"\bdiskpart\b",
        r"\bmkfs\b",
        r"\bkill\s+",
        r"\btaskkill\b",
        r"\bsudo\b",
        r"\bchmod\s+777\b",
        r"\brun\s+as\s+admin\b",
    )
)

_YES_WORDS = frozenset(
    {
        "yes",
        "yeah",
        "yep",
        "yup",
        "y",
        "ok",
        "okay",
        "sure",
        "confirm",
        "confirmed",
        "proceed",
        "do it",
        "go ahead",
        "go for it",
        "affirmative",
        "please do",
    }
)

_NO_WORDS = frozenset(
    {
        "no",
        "nope",
        "nah",
        "n",
        "cancel",
        "cancelled",
        "canceled",
        "stop",
        "don't",
        "dont",
        "do not",
        "never",
        "negative",
        "abort",
        "decline",
    }
)


@runtime_checkable
class Confirmer(Protocol):
    """Decision provider for the ask-first gate (voice, click, or test double)."""

    def confirm(self, *, prompt: str, proposed_action: str) -> bool:
        """Return True to proceed, False to cancel (no / unclear / timeout)."""
        ...


@dataclass
class FixedConfirmer:
    """Deterministic confirmer for tests and headless defaults."""

    answer: bool = False
    calls: list[tuple[str, str]] = field(default_factory=list)

    def confirm(self, *, prompt: str, proposed_action: str) -> bool:
        self.calls.append((prompt, proposed_action))
        return self.answer


@dataclass
class CallableConfirmer:
    """Wrap a function or lambda as a Confirmer."""

    decide: Callable[[str, str], bool]
    calls: list[tuple[str, str]] = field(default_factory=list)

    def confirm(self, *, prompt: str, proposed_action: str) -> bool:
        self.calls.append((prompt, proposed_action))
        # Protocol: unclear → False (safe decline).
        return bool(self.decide(prompt, proposed_action))


@dataclass
class OverlayClickConfirmer:
    """Overlay Yes/No click backup (FakeOverlay / Aurora).

    Prefers a queued decision, then blocks on ``wait_confirm`` when available.
    Unclear / timeout → ``default`` (False = decline).
    """

    overlay: object
    default: bool = False
    timeout_s: float = 30.0
    calls: list[tuple[str, str]] = field(default_factory=list)

    def confirm(self, *, prompt: str, proposed_action: str) -> bool:
        self.calls.append((prompt, proposed_action))
        take = getattr(self.overlay, "take_confirm_decision", None)
        if callable(take):
            decision = take()
            if decision is not None:
                return bool(decision)
        wait = getattr(self.overlay, "wait_confirm", None)
        if callable(wait):
            decision = wait(timeout_s=self.timeout_s)
            if decision is not None:
                return bool(decision)
        return self.default


@dataclass
class VoiceOrClickConfirmer:
    """Short voice yes/no with optional overlay click backup.

    Order: non-blocking overlay take → record+STT → overlay take again →
    parse_yes_no → optional blocking overlay wait → default (False).
    """

    overlay: object | None = None
    recorder: object | None = None
    transcriber: object | None = None
    default: bool = False
    overlay_timeout_s: float = 0.05
    calls: list[tuple[str, str]] = field(default_factory=list)

    def confirm(self, *, prompt: str, proposed_action: str) -> bool:
        self.calls.append((prompt, proposed_action))
        clicked = self._overlay_take()
        if clicked is not None:
            return clicked

        if self.recorder is not None and self.transcriber is not None:
            text = self._listen_once()
            clicked = self._overlay_take()
            if clicked is not None:
                return clicked
            parsed = parse_yes_no(text)
            if parsed is not None:
                return parsed
            # Unclear voice: brief overlay wait for late click, then decline.
            waited = self._overlay_wait(self.overlay_timeout_s)
            if waited is not None:
                return waited
            return self.default

        # Overlay-only (no mic): block until click or timeout.
        waited = self._overlay_wait(30.0)
        if waited is not None:
            return waited
        return self.default

    def _overlay_take(self) -> bool | None:
        if self.overlay is None:
            return None
        take = getattr(self.overlay, "take_confirm_decision", None)
        if callable(take):
            decision = take()
            if decision is not None:
                return bool(decision)
        return None

    def _overlay_wait(self, timeout_s: float) -> bool | None:
        if self.overlay is None or timeout_s <= 0:
            return None
        wait = getattr(self.overlay, "wait_confirm", None)
        if not callable(wait):
            return None
        decision = wait(timeout_s=timeout_s)
        if decision is not None:
            return bool(decision)
        return None

    def _listen_once(self) -> str:
        try:
            record = self.recorder.record_until_silence()  # type: ignore[union-attr]
            if record is None or getattr(record, "audio", None) is None:
                return ""
            if getattr(record.audio, "size", 0) == 0:
                return ""
            sr = int(getattr(record, "sample_rate", 16_000) or 16_000)
            text = self.transcriber.transcribe(  # type: ignore[union-attr]
                record.audio, sample_rate=sr
            )
            return (text or "").strip()
        except Exception:  # noqa: BLE001 — confirmation must not crash the loop
            return ""


def is_secret_request(command: str) -> bool:
    """True when the utterance asks about passwords / keys / credentials."""
    lower = (command or "").lower()
    if not lower.strip():
        return False
    # "secret" alone is too broad ("secret santa"); require stronger tokens.
    return any(tok in lower for tok in _SECRET_TOKENS) or (
        "secret" in lower
        and any(
            w in lower for w in ("password", "key", "credential", "token", "file")
        )
    )


def is_risky_request(command: str) -> bool:
    """True when the utterance looks destructive / system-level / outward."""
    text = (command or "").strip()
    if not text or is_secret_request(text):
        return False
    return any(p.search(text) for p in _RISKY_PATTERNS)


def describe_risky_action(command: str) -> str:
    """Short human-readable summary of a risky command for the overlay."""
    text = (command or "").strip()
    if not text:
        return "Perform a risky action"
    lower = text.lower()

    if re.search(r"\b(delete|erase|remove|wipe|unlink)\b", lower) or re.search(
        r"\brm\s", lower
    ) or re.search(r"\bdel\s", lower):
        target = _tail_after(
            text,
            (
                "delete",
                "erase",
                "remove",
                "wipe",
                "unlink",
                "rm -rf",
                "rm -r",
                "rm",
                "del",
            ),
        )
        return f"Delete {target}" if target else "Delete files"

    if re.search(r"\boverwrite\b", lower):
        target = _tail_after(text, ("overwrite",))
        return f"Overwrite {target}" if target else "Overwrite a file"

    if re.search(r"\bformat\b", lower):
        target = _tail_after(text, ("format",))
        return f"Format {target}" if target else "Format a drive"

    if re.search(r"\bshutdown\b", lower):
        return "Shut down the computer"

    if re.search(r"\breboot\b", lower):
        return "Reboot the computer"

    if re.search(r"\bsend\s+(an?\s+)?email\b", lower):
        return "Send an email"

    if re.search(r"\bsend\s+a\s+message\b", lower):
        return "Send a message"

    if re.search(r"\buninstall\b", lower):
        target = _tail_after(text, ("uninstall",))
        return f"Uninstall {target}" if target else "Uninstall software"

    if re.search(r"\bregistry\b|\bregedit\b", lower):
        return "Change the Windows registry"

    if re.search(r"\b(kill|taskkill)\b", lower):
        target = _tail_after(text, ("taskkill", "kill"))
        return f"Kill process {target}" if target else "Kill a process"

    # Fallback: show the full command (exact proposed action).
    return text[0].upper() + text[1:] if text else text


def confirmation_prompt(proposed_action: str) -> str:
    """Spoken yes/no prompt for the proposed action."""
    action = (proposed_action or "this").strip().rstrip(".?!")
    return f"{action}? Say yes or no."


def sanitize_user_command(command: str) -> str:
    """Strip spoof confirmation prefixes from inbound user text.

    Never treats a user-supplied prefix as authorization — callers must pass
    ``confirmed=True`` to ``brain.ask`` only after a real Confirmer yes.
    """
    body, _ = strip_confirmed(command)
    return body


def strip_confirmed(command: str) -> tuple[str, bool]:
    """Return (command_without_prefix, prefix_was_present).

    The boolean only means the text started with CONFIRMED: — it is **not**
    an authorization signal. Use ``brain.ask(..., confirmed=True)`` for that.
    """
    text = (command or "").strip()
    if text.upper().startswith(CONFIRMED_PREFIX):
        rest = text[len(CONFIRMED_PREFIX) :].strip()
        return rest, True
    return text, False


def is_confirmed(command: str) -> bool:
    """Deprecated name: True only if the *text* starts with CONFIRMED:.

    Does not mean the action is authorized. Prefer ``confirmed=`` on ask().
    """
    return (command or "").strip().upper().startswith(CONFIRMED_PREFIX)


def as_confirmed(command: str) -> str:
    """Deprecated: prefix helper kept for tests. Prefer confirmed=True on ask()."""
    body = sanitize_user_command(command)
    if not body:
        return CONFIRMED_PREFIX
    return f"{CONFIRMED_PREFIX} {body}"


def parse_yes_no(text: str) -> bool | None:
    """Parse a short voice/text reply into yes/no.

    Returns True (yes), False (no), or None when unclear.
    """
    raw = (text or "").strip().lower()
    if not raw:
        return None
    # Normalize punctuation and common STT contractions.
    cleaned = re.sub(r"[^\w\s']", " ", raw)
    cleaned = cleaned.replace("'", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    # "don't" → "dont" after stripping apostrophe.
    if cleaned in _YES_WORDS:
        return True
    if cleaned in _NO_WORDS:
        return False

    for phrase in _YES_WORDS:
        if " " in phrase and phrase in cleaned:
            return True
    for phrase in _NO_WORDS:
        if " " in phrase and phrase in cleaned:
            return False

    tokens = cleaned.split()
    if not tokens:
        return None
    # Avoid treating the prompt echo "yes or no" as a decision.
    if "or" in tokens and "yes" in tokens and "no" in tokens:
        return None
    if tokens[0] in _YES_WORDS:
        return True
    if tokens[0] in _NO_WORDS:
        return False
    if any(t in ("yes", "yeah", "yep", "yup") for t in tokens) and not any(
        t in ("no", "nope", "nah", "cancel") for t in tokens
    ):
        return True
    if any(
        t in ("no", "nope", "nah", "cancel", "stop", "dont") for t in tokens
    ) and not any(t in ("yes", "yeah", "yep") for t in tokens):
        return False
    return None


def ask_brain(brain: Any, command: str, *, confirmed: bool = False) -> Any:
    """Call ``brain.ask`` with confirmed= when supported (forward-compatible)."""
    try:
        return brain.ask(command, confirmed=confirmed)
    except TypeError:
        # Test doubles / older brains without the kwarg.
        return brain.ask(command)


def _tail_after(text: str, markers: tuple[str, ...]) -> str:
    lower = text.lower()
    for marker in markers:
        idx = lower.find(marker.lower())
        if idx >= 0:
            tail = text[idx + len(marker) :].strip(" \t:.-")
            if tail:
                return tail
    return text.strip()
