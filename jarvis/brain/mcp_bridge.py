"""JARVIS tool bridge for the Claude CLI brain (issue 15).

Exposes JARVIS's own capabilities — ``spotify``, ``apps``, ``windows``,
``media``, ``memory`` and ``google_read`` — as MCP tools the heavy Claude
brain can call mid-turn, so a multi-domain request ("open spotify and play
the next track") no longer dies on the old system-prompt ban.

Transport — Option A (in-process HTTP MCP server)
-------------------------------------------------
The MCP spec's stdio transport spawns the server as the CLI's *own* child
process, which shares no memory with the running JARVIS process — it could not
call the live confirmer or publish to the in-process :class:`EventBus`. Instead
JARVIS hosts the MCP server **inside its own process** over Streamable HTTP and
registers it with the Claude CLI by URL (``--mcp-config``). Every ``tools/call``
therefore runs on JARVIS's own threads with DIRECT access to the real domain
handlers, the real confirmer, and the real bus — no IPC layer, no serialization,
so the confirm gate and Step* events are genuinely correct rather than stubbed.
Claude Code supports stdio, SSE and HTTP MCP transports; this uses HTTP.

Safety (non-negotiable)
-----------------------
Every side-effecting tool call passes through the SAME
:mod:`jarvis.confirm` logic as a direct voice command:

* ``is_secret_request`` → hard-denied unconditionally; the handler never runs.
* ``is_risky_request`` (delete / overwrite / send / uninstall / …) → ask-first
  via the injected :class:`~jarvis.confirm.Confirmer`; declined ⇒ never runs.
* a small bridge-scoped tightening also gates the destructive domain verbs the
  generic word-list omits ("close" a window, "forget" a note) — this only
  *adds* confirmation, it never weakens :mod:`jarvis.confirm`.

Each call emits :class:`StepStarted` then :class:`StepFinished` (or
:class:`StepFailed` on error / denial / decline) on the bus.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from jarvis.confirm import (
    confirmation_prompt,
    describe_risky_action,
    is_risky_request,
    is_secret_request,
)
from jarvis.events import ConfirmRequested, StepFailed, StepFinished, StepStarted
from jarvis.plain_replies import plain_error_reply

# MCP protocol version we advertise when the client does not pin one.
PROTOCOL_VERSION = "2025-06-18"
# MCP server name → tool ids the CLI sees are ``mcp__<server>__<tool>``.
SERVER_NAME = "jarvis"

SECRET_REFUSAL = "I never touch passwords, API keys, or credentials."
CANCELLED_REPLY = "Okay, cancelled."

# Destructive domain verbs the generic jarvis.confirm word-list does not flag
# but the bridge must still gate (task: "delete/close/overwrite/send must not
# execute unconfirmed"). Bridge-scoped only — the voice path is untouched.
_BRIDGE_EXTRA_RISKY = re.compile(r"\b(?:close|forget)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Tool catalogue
# ---------------------------------------------------------------------------

# name → one-line description shown to the model. Order defines tools/list order.
_TOOLS: tuple[tuple[str, str], ...] = (
    (
        "spotify",
        "Control Spotify playback: play/pause/resume, skip to the next track, "
        "play a named song/artist/playlist, say what's now playing, or set the "
        "volume. Prefer this over shell for music. Pass the request in plain "
        "English, e.g. 'play the next track' or 'pause the music'.",
    ),
    (
        "apps",
        "Open or focus a desktop app (focuses an existing window if the app is "
        "already running, else launches it once). Prefer this over shell for "
        "opening apps. Example: 'open spotify', 'focus chrome'.",
    ),
    (
        "windows",
        "Control the active desktop windows: focus, minimize, maximize, snap "
        "left/right, fullscreen, or close a window. Prefer this over shell. "
        "Example: 'minimize chrome', 'snap vlc left', 'close notepad'.",
    ),
    (
        "media",
        "Find a local media file in the user's folders and open it in the real "
        "player (never pretend it opened). Prefer this over shell for playing "
        "local video/audio. Example: 'play the movie interstellar', "
        "'play blade runner fullscreen'.",
    ),
    (
        "system",
        "Adjust screen brightness (set an absolute percent, or step up/down) and "
        "open the most recent capture (e.g. the last screen recording). Prefer "
        "this over shell. Example: 'set brightness to 50', 'dim brightness to "
        "zero', 'open the last screen recording'.",
    ),
    (
        "memory",
        "The user's long-term memory notes: remember a new fact, recall stored "
        "facts, or forget a note. Example: 'remember that my sister's birthday "
        "is in May', 'what do you remember about my car', 'forget my old address'.",
    ),
    (
        "google_read",
        "Read-only Gmail and Google Calendar: summarize unread mail, search "
        "mail, summarize a thread, today's schedule, the next event, or free "
        "time. READ ONLY — it will refuse to send, reply, forward, or create "
        "events. Example: 'any unread email from my bank', 'what's on my "
        "calendar today'.",
    ),
)

TOOL_NAMES: tuple[str, ...] = tuple(name for name, _ in _TOOLS)


def _command_schema(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "The user's request in plain English for this domain — "
                    + description
                ),
            }
        },
        "required": ["command"],
        "additionalProperties": False,
    }


def tool_definitions() -> list[dict[str, Any]]:
    """MCP ``tools/list`` payload for the six JARVIS domains."""
    return [
        {
            "name": name,
            "description": description,
            "inputSchema": _command_schema(description),
        }
        for name, description in _TOOLS
    ]


def allowed_tool_ids() -> list[str]:
    """CLI ``--allowedTools`` identifiers for the six bridge tools."""
    return [f"mcp__{SERVER_NAME}__{name}" for name in TOOL_NAMES]


# ---------------------------------------------------------------------------
# Tool-call result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCallResult:
    """Outcome of one bridge tool call (maps to an MCP tool result)."""

    text: str
    is_error: bool = False
    denied: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


@dataclass
class JarvisToolBridge:
    """In-process MCP server exposing the six JARVIS domains as tools.

    Handlers are the *existing* controllers/handlers (thin adapters, not
    reimplementations); each is optional so tests can wire only what they need.
    ``confirmer`` and ``bus`` are the same objects the voice pipeline uses, so
    the confirm gate and Step* events are the real thing.
    """

    bus: Any = None
    confirmer: Any = None
    spotify: Any = None
    apps: Any = None
    windows: Any = None
    media: Any = None
    system: Any = None
    memory: Any = None
    google: Any = None

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _httpd: Any = field(default=None, init=False, repr=False)
    _thread: Any = field(default=None, init=False, repr=False)
    _port: int | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )
    _call_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    # -- domain dispatch ----------------------------------------------------

    def _handler_for(self, name: str) -> Any:
        return {
            "spotify": self.spotify,
            "apps": self.apps,
            "windows": self.windows,
            "media": self.media,
            "system": self.system,
            "memory": self.memory,
            "google_read": self.google,
        }.get(name)

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> ToolCallResult:
        """Gate → dispatch → map one tool call (thread-safe, serialized).

        The gate is authoritative: a secret request is hard-denied and a risky
        request that is not confirmed NEVER reaches the handler.
        """
        command = str((arguments or {}).get("command") or "").strip()
        # Serialize so confirm prompts and bus ordering never interleave when
        # the CLI fires overlapping tool calls.
        with self._call_lock:
            self._publish(StepStarted(name=name, detail=command))

            # 1. Secrets — hard-deny, unconditional, never execute.
            if is_secret_request(command):
                self._publish(
                    StepFailed(name=name, detail=command, error="secret_denied")
                )
                return ToolCallResult(
                    text=SECRET_REFUSAL,
                    is_error=True,
                    denied=True,
                    error="secret_denied",
                )

            # 2. Risky — ask-first via the real confirmer; decline ⇒ no run.
            needs, proposed = self._needs_confirm(command)
            if needs and not self._confirm(proposed):
                self._publish(
                    StepFailed(
                        name=name, detail=command, error="confirmation_declined"
                    )
                )
                return ToolCallResult(
                    text=CANCELLED_REPLY,
                    is_error=True,
                    error="confirmation_declined",
                )

            handler = self._handler_for(name)
            if handler is None:
                self._publish(
                    StepFailed(name=name, detail=command, error="unavailable")
                )
                return ToolCallResult(
                    text=f"The {name} tool isn't available right now.",
                    is_error=True,
                    error="unavailable",
                )

            # 3. Dispatch into the existing handler.
            try:
                result = handler.try_handle(command)
            except Exception as exc:  # noqa: BLE001 — boundary: speak plain, never crash
                err = type(exc).__name__
                self._publish(StepFailed(name=name, detail=command, error=err))
                return ToolCallResult(
                    text=plain_error_reply(err, fallback="Something went wrong."),
                    is_error=True,
                    error=err,
                )

            if result is None:
                # Handler did not recognize the command for its domain.
                self._publish(
                    StepFailed(name=name, detail=command, error="unhandled")
                )
                return ToolCallResult(
                    text=f"I couldn't do that with the {name} tool.",
                    is_error=True,
                    error="unhandled",
                )

            return self._finish(name, command, result)

    def _finish(self, name: str, command: str, result: Any) -> ToolCallResult:
        reply = (getattr(result, "reply", "") or "").strip()
        ok = bool(getattr(result, "ok", True))
        denied = bool(getattr(result, "denied", False))
        err = getattr(result, "error", None)
        if ok and not denied:
            self._publish(StepFinished(name=name, detail=reply or command))
            return ToolCallResult(text=reply or "Done.", is_error=False)
        # Denied (e.g. google write refusal) or a plain handler failure.
        self._publish(
            StepFailed(name=name, detail=command, error=str(err or "failed"))
        )
        text = reply or plain_error_reply(
            str(err) if err else None, fallback="Something went wrong."
        )
        return ToolCallResult(text=text, is_error=True, denied=denied, error=err)

    # -- confirm gate -------------------------------------------------------

    @staticmethod
    def _needs_confirm(command: str) -> tuple[bool, str]:
        if is_risky_request(command) or _BRIDGE_EXTRA_RISKY.search(command):
            return True, describe_risky_action(command)
        return False, ""

    def _confirm(self, proposed: str) -> bool:
        prompt = confirmation_prompt(proposed)
        self._publish(ConfirmRequested(proposed_action=proposed, prompt=prompt))
        confirmer = self.confirmer
        if confirmer is None:
            # No decision channel → safe default is decline (never auto-run).
            return False
        try:
            return bool(confirmer.confirm(prompt=prompt, proposed_action=proposed))
        except Exception:  # noqa: BLE001 — confirmer failure ⇒ decline
            return False

    def _publish(self, event: object) -> None:
        bus = self.bus
        if bus is None:
            return
        try:
            bus.publish(event)
        except Exception:  # noqa: BLE001 — bus is observability, never control flow
            pass

    # -- MCP JSON-RPC -------------------------------------------------------

    def handle_jsonrpc(self, message: Any) -> dict[str, Any] | None:
        """Dispatch one JSON-RPC message; return a response, or None for a
        notification (no ``id``)."""
        if not isinstance(message, dict):
            return _rpc_error(None, -32600, "Invalid Request")
        method = message.get("method")
        mid = message.get("id")
        is_request = "id" in message
        params = message.get("params") or {}

        if method == "initialize":
            requested = params.get("protocolVersion")
            return _rpc_result(
                mid,
                {
                    "protocolVersion": requested or PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
                    "instructions": (
                        "JARVIS's own tools: spotify, apps, windows, media, "
                        "system, memory, google_read. Prefer them over shell for "
                        "those domains. google_read is read-only."
                    ),
                },
            )
        if method == "ping":
            return _rpc_result(mid, {})
        if method == "tools/list":
            return _rpc_result(mid, {"tools": tool_definitions()})
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            if name not in TOOL_NAMES:
                return _rpc_result(
                    mid,
                    {
                        "content": [
                            {"type": "text", "text": f"Unknown tool: {name}"}
                        ],
                        "isError": True,
                    },
                )
            res = self.call_tool(name, arguments)
            return _rpc_result(
                mid,
                {
                    "content": [{"type": "text", "text": res.text}],
                    "isError": res.is_error,
                },
            )
        if not is_request:
            # Any other notification (e.g. notifications/initialized) — ack only.
            return None
        return _rpc_error(mid, -32601, f"Method not found: {method}")

    # -- HTTP server lifecycle ---------------------------------------------

    def ensure_started(self) -> None:
        """Bind and serve the in-process MCP HTTP server (idempotent)."""
        with self._lock:
            if self._httpd is not None:
                return
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), _MCPRequestHandler)
            httpd.bridge = self  # type: ignore[attr-defined]
            self._port = int(httpd.server_address[1])
            self._httpd = httpd
            thread = threading.Thread(
                target=httpd.serve_forever, name="jarvis-mcp", daemon=True
            )
            thread.start()
            self._thread = thread

    def stop(self) -> None:
        with self._lock:
            httpd = self._httpd
            self._httpd = None
            self._port = None
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:  # noqa: BLE001
                pass
            try:
                httpd.server_close()
            except Exception:  # noqa: BLE001
                pass

    @property
    def port(self) -> int | None:
        return self._port

    @property
    def url(self) -> str:
        if self._port is None:
            raise RuntimeError("MCP bridge not started")
        return f"http://127.0.0.1:{self._port}/mcp"

    def mcp_config(self) -> dict[str, Any]:
        """`--mcp-config` object registering this server with the Claude CLI."""
        return {
            "mcpServers": {
                SERVER_NAME: {"type": "http", "url": self.url},
            }
        }

    def mcp_config_json(self) -> str:
        return json.dumps(self.mcp_config())

    @staticmethod
    def allowed_tool_ids() -> list[str]:  # type: ignore[override]
        return allowed_tool_ids()


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _rpc_result(mid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _rpc_error(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


# ---------------------------------------------------------------------------
# HTTP handler (Streamable HTTP, JSON responses)
# ---------------------------------------------------------------------------


class _MCPRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def _bridge(self) -> JarvisToolBridge:
        return self.server.bridge  # type: ignore[attr-defined]

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError):
            self._send_json(_rpc_error(None, -32700, "Parse error"))
            return

        bridge = self._bridge
        if isinstance(payload, list):
            responses = [
                r
                for r in (bridge.handle_jsonrpc(m) for m in payload)
                if r is not None
            ]
            if not responses:
                self._send_empty(202)
            else:
                self._send_json(responses)
            return

        if not isinstance(payload, dict):
            self._send_json(_rpc_error(None, -32600, "Invalid Request"))
            return

        response = bridge.handle_jsonrpc(payload)
        if response is None:
            self._send_empty(202)
            return
        extra = None
        if payload.get("method") == "initialize":
            extra = {"Mcp-Session-Id": bridge.session_id}
        self._send_json(response, extra_headers=extra)

    def do_GET(self) -> None:  # noqa: N802
        # No server-initiated SSE stream is offered at this endpoint.
        self._send_empty(405)

    def do_DELETE(self) -> None:  # noqa: N802
        self._send_empty(204)

    # -- response helpers ---------------------------------------------------

    def _send_json(
        self, obj: Any, *, extra_headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args: Any) -> None:  # silence stderr access log
        return


__all__ = [
    "JarvisToolBridge",
    "ToolCallResult",
    "TOOL_NAMES",
    "allowed_tool_ids",
    "tool_definitions",
]
