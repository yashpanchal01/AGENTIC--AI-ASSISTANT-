"""Plain-language spoken replies for failures and refusals.

Never surface stack traces, exception type names, or empty silence when
JARVIS can't complete a command. Messages are short and speakable.
"""

from __future__ import annotations

# Canonical spoken lines (acceptance / PRD wording).
BRAIN_UNREACHABLE = (
    "My brain is unreachable right now — check your internet connection."
)
EMPTY_TRANSCRIPT = "I heard you, but I couldn't understand that."
NO_SPEECH = "I didn't catch that."
GENERIC_FAILURE = "Something went wrong, and I couldn't finish that."
BRAIN_EXCEPTION = "Something went wrong talking to my brain."
STT_FAILED = "I couldn't transcribe that."
TIMEOUT = "That took too long and I had to stop."
CLAUDE_NOT_FOUND = "I can't reach my brain — Claude CLI is not installed."
# Long-running tasks (issue 10 / PRD stories 44–45)
ON_IT = "On it."
CANCELLED = "Cancelled."
NOTHING_TO_CANCEL = "Nothing to cancel."
STILL_WORKING = "I'm still working on that. Say cancel to stop."
ALREADY_FINISHED = "That already finished."

_ERROR_REPLIES: dict[str, str] = {
    "brain_unreachable": BRAIN_UNREACHABLE,
    "empty_transcript": EMPTY_TRANSCRIPT,
    "no_speech": NO_SPEECH,
    "stt_failed": STT_FAILED,
    "timeout": TIMEOUT,
    "claude_not_found": CLAUDE_NOT_FOUND,
    "cancelled": CANCELLED,
    "tool_failed": GENERIC_FAILURE,
    "not_found": "I couldn't find that.",
}


def plain_error_reply(error: str | None, *, fallback: str | None = None) -> str:
    """Map a machine error code to a short spoken sentence."""
    if error and error in _ERROR_REPLIES:
        return _ERROR_REPLIES[error]
    if fallback and fallback.strip():
        return fallback.strip()
    return GENERIC_FAILURE


def looks_like_network_failure(exc: BaseException | str | None) -> bool:
    """Heuristic: exception or text looks like connectivity, not app logic."""
    if exc is None:
        return False
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        # OSError is broad; only treat clearly network-ish subclasses/messages.
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return True
        # Fall through to message check for other OSError.
    text = str(exc).lower() if not isinstance(exc, str) else exc.lower()
    if not text:
        return False
    tokens = (
        "network is unreachable",
        "network unreachable",
        "failed to resolve",
        "name or service not known",
        "nodename nor servname",
        "getaddrinfo failed",
        "temporary failure in name resolution",
        "connection refused",
        "connection reset",
        "connection timed out",
        "timed out",
        "no route to host",
        "could not connect",
        "errno 11001",  # WSAHOST_NOT_FOUND on Windows
        "errno 10051",  # WSAENETUNREACH
        "errno 10060",  # WSAETIMEDOUT
        "enotfound",
        "eai_again",
        "fetch failed",
        "socket hang up",
        "offline",
        "dns",
        "ssl",
        "unreachable",
    )
    return any(t in text for t in tokens)
