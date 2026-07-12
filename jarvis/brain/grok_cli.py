"""Grok CLI headless brain adapter.

Spawns `grok -p` with JSON output, tool allowlist, auto-approve for the safe
tier, and session resume so one long-lived conversation carries context across
commands. Drop-in replacement for ClaudeCodeBrain when Claude limits hit.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.config import JARVIS_SYSTEM_PROMPT, JarvisConfig
from jarvis.events import StepFinished, StepStarted
from jarvis.confirm import (
    confirmation_prompt,
    describe_risky_action,
    is_risky_request,
    is_secret_request,
    sanitize_user_command,
)
from jarvis.plain_replies import BRAIN_UNREACHABLE, looks_like_network_failure
from jarvis.types import Action, BrainTurn

# Grok headless tool IDs (not Claude Code names).
DEFAULT_GROK_SAFE_TOOLS: tuple[str, ...] = (
    "run_terminal_cmd",
    "read_file",
    "list_dir",
    "grep",
    "search_replace",
    "web_search",
    "web_fetch",
)


@dataclass
class GrokCliBrain:
    """Real brain: Grok CLI behind the Brain protocol.

    Cancel policy mirrors ClaudeCodeBrain: ``cancel()`` kills the process tree;
    ``session_id`` is retained after cancel for continuity.
    """

    config: JarvisConfig = field(default_factory=JarvisConfig)
    session_id: str | None = None
    # Optional EventBus (issue 12): StepStarted/StepFinished per reported tool
    # call. Grok's JSON arrives at end-of-run, so steps are emitted as soon as
    # the payload is parsed (Grok reports tools post-hoc, unlike Claude).
    bus: Any = None
    _grok_bin: str | None = field(default=None, init=False, repr=False)
    _proc: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    _proc_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _cancel: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )

    def cancel(self) -> None:
        """Abort the in-flight Grok CLI process tree (long-task cancel)."""
        self._cancel.set()
        with self._proc_lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            self._kill_proc(proc)

    def ask(self, command: str, *, confirmed: bool = False) -> BrainTurn:
        if self._cancel.is_set():
            self._cancel.clear()
            return BrainTurn(
                reply="Cancelled.",
                ok=False,
                error="cancelled",
                session_id=self.session_id,
            )

        body = sanitize_user_command(command)
        if is_secret_request(body):
            return BrainTurn(
                reply="I never touch passwords, API keys, or credentials.",
                actions=(),
                session_id=self.session_id,
                denied=True,
                ok=True,
            )
        if is_risky_request(body) and not confirmed:
            proposed = describe_risky_action(body)
            return BrainTurn(
                reply=confirmation_prompt(proposed),
                actions=(),
                session_id=self.session_id,
                needs_confirmation=True,
                proposed_action=proposed,
                ok=True,
            )

        args = self._build_args(body)
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(self.config.cwd),
            )
        except FileNotFoundError:
            return BrainTurn(
                reply="I can't reach my brain — Grok CLI is not installed.",
                ok=False,
                error="grok_not_found",
                session_id=self.session_id,
            )

        with self._proc_lock:
            self._proc = proc

        io_box: dict[str, str | None] = {"stdout": None, "stderr": None}

        def _drain() -> None:
            out, err = proc.communicate()
            io_box["stdout"] = out
            io_box["stderr"] = err

        reader = threading.Thread(target=_drain, name="grok-io", daemon=True)
        reader.start()

        try:
            deadline = time.monotonic() + 300
            while reader.is_alive():
                if self._cancel.is_set():
                    self._kill_proc(proc)
                    reader.join(timeout=2)
                    return BrainTurn(
                        reply="Cancelled.",
                        ok=False,
                        error="cancelled",
                        session_id=self.session_id,
                    )
                if time.monotonic() >= deadline:
                    self._kill_proc(proc)
                    reader.join(timeout=2)
                    return BrainTurn(
                        reply="That took too long and I had to stop.",
                        ok=False,
                        error="timeout",
                        session_id=self.session_id,
                    )
                reader.join(timeout=0.05)

            if self._cancel.is_set():
                return BrainTurn(
                    reply="Cancelled.",
                    ok=False,
                    error="cancelled",
                    session_id=self.session_id,
                )

            stdout = io_box.get("stdout") or ""
            stderr = io_box.get("stderr") or ""
            turn = parse_grok_output(stdout)
            self._publish_steps(turn)
            stderr_s = stderr.strip()
            combined_err = " ".join(
                p for p in (turn.error or "", turn.reply or "", stderr_s) if p
            )

            if turn.session_id:
                self.session_id = turn.session_id

            session = self.session_id or turn.session_id

            if looks_like_network_failure(combined_err):
                return BrainTurn(
                    reply=BRAIN_UNREACHABLE,
                    actions=turn.actions,
                    session_id=session,
                    denied=turn.denied,
                    ok=False,
                    error="brain_unreachable",
                )

            if proc.returncode is not None and proc.returncode != 0:
                if self._cancel.is_set():
                    return BrainTurn(
                        reply="Cancelled.",
                        ok=False,
                        error="cancelled",
                        session_id=session,
                    )
                reply = _spoken_error_reply(turn.reply, turn.error, stderr_s)
                return BrainTurn(
                    reply=reply,
                    actions=turn.actions,
                    session_id=session,
                    denied=turn.denied,
                    ok=False,
                    error=turn.error or f"exit_{proc.returncode}",
                )

            if not turn.reply and turn.ok:
                return BrainTurn(
                    reply="Done.",
                    actions=turn.actions,
                    session_id=session,
                    denied=turn.denied,
                    ok=True,
                )

            return BrainTurn(
                reply=turn.reply,
                actions=turn.actions,
                session_id=session,
                denied=turn.denied,
                needs_confirmation=turn.needs_confirmation,
                proposed_action=turn.proposed_action,
                ok=turn.ok,
                error=turn.error,
            )
        finally:
            with self._proc_lock:
                if self._proc is proc:
                    self._proc = None
            self._cancel.clear()

    def _publish_steps(self, turn: BrainTurn) -> None:
        """Emit StepStarted/StepFinished per tool call Grok reported (issue 12)."""
        bus = self.bus
        if bus is None:
            return
        for action in turn.actions:
            try:
                bus.publish(StepStarted(name=action.name, detail=action.detail))
                bus.publish(StepFinished(name=action.name, detail=action.detail))
            except Exception:  # noqa: BLE001 — bus must never break a turn
                pass

    @staticmethod
    def _kill_proc(proc: subprocess.Popen[str]) -> None:
        import sys

        pid = getattr(proc, "pid", None)
        if pid and sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
            except Exception:  # noqa: BLE001
                pass
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass

    def _build_args(self, command: str) -> list[str]:
        bin_path = self._resolve_grok()
        system = self.config.system_prompt or JARVIS_SYSTEM_PROMPT
        if self.config.approved_folders:
            folders = "; ".join(str(p) for p in self.config.approved_folders)
            system = (
                f"{system} Approved folders for autonomous file work: {folders}. "
                "Do not write or delete outside those folders without asking first. "
                "Never run destructive shell commands (delete system paths, format, "
                "shutdown, registry edits, privilege escalation)."
            )
        # Markdown memory digest (issue 07): remembered facts ride in the
        # system prompt so later sessions use them without being retold.
        from jarvis.memory.store import memory_context_for_prompt

        memory_ctx = memory_context_for_prompt(self.config.memory_dir)
        if memory_ctx:
            system = f"{system} {memory_ctx}"
        # Grok CLI gotchas (2026-07):
        # - --tools allowlist breaks session create (run_terminal_cmd constraint).
        # - --disallowed-tools Agent (or similar) also breaks the same constraint.
        # Reliable path: full default tools + --always-approve + --no-subagents.
        args = [
            bin_path,
            "-p",
            command,
            "--output-format",
            "json",
            "--always-approve",
            "--rules",
            system,
            "--cwd",
            str(self.config.cwd),
            "--no-subagents",
        ]
        if self.session_id:
            args.extend(["--resume", self.session_id])
        model = (self.config.grok_model or "").strip()
        if model and model not in ("default", "sonnet", "opus", "haiku"):
            args.extend(["--model", model])
        return args

    def _resolve_grok(self) -> str:
        if self._grok_bin:
            return self._grok_bin
        configured = self.config.grok_bin
        if Path(configured).is_file():
            self._grok_bin = configured
            return configured
        found = shutil.which(configured)
        if found:
            self._grok_bin = found
            return found
        # Common install location when PATH is incomplete (this machine).
        home_bin = Path.home() / ".grok" / "bin" / "grok.exe"
        if home_bin.is_file():
            self._grok_bin = str(home_bin)
            return self._grok_bin
        self._grok_bin = configured
        return configured

    def reset_session(self) -> None:
        """Start a fresh conversation (drop resume id)."""
        self.session_id = None


def _spoken_error_reply(
    reply: str | None, error: str | None, stderr: str = ""
) -> str:
    """Short plain-language failure for voice; keep useful signal, not dumps."""
    for candidate in (reply, error, stderr):
        text = (candidate or "").strip()
        if not text or "Traceback" in text:
            continue
        lower = text.lower()
        if "couldn't create session" in lower or "agent building failed" in lower:
            return "My brain failed to start a session. Check the Grok CLI setup."
        if "not authenticated" in lower or "login" in lower and "auth" in lower:
            return "I'm not signed in to Grok. Run grok login and try again."
        if "rate limit" in lower or "usage limit" in lower or "session limit" in lower:
            return "I've hit a Grok usage limit. Try again later."
        # Prefer first sentence / short slice
        one = text.split("\n", 1)[0].strip()
        if len(one) > 160:
            one = one[:157] + "..."
        if one:
            return one
    return "Something went wrong talking to my brain."


def parse_grok_output(stdout: str) -> BrainTurn:
    """Parse Grok headless ``--output-format json`` (or plain text fallback)."""
    text = (stdout or "").strip()
    if not text:
        return BrainTurn(reply="", ok=True)

    # Prefer the last JSON object in stdout (ignore leading log noise).
    for candidate in _json_candidates(text):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("type") == "error" or (
            "message" in data and "text" not in data and "sessionId" not in data
        ):
            msg = str(data.get("message") or data.get("error") or "brain error")
            return BrainTurn(reply=msg, ok=False, error=msg)
        reply = data.get("text")
        if reply is None and "result" in data:
            reply = data.get("result")
        sid = data.get("sessionId") or data.get("session_id")
        actions = _actions_from_payload(data)
        if isinstance(reply, str) or sid or actions:
            return BrainTurn(
                reply=(reply or "").strip() if isinstance(reply, str) else "",
                actions=tuple(actions),
                session_id=str(sid) if sid else None,
                ok=True,
            )

    # Streaming-json NDJSON: join text chunks.
    if "\n" in text and '"type"' in text:
        chunks: list[str] = []
        sid: str | None = None
        err: str | None = None
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            et = ev.get("type")
            if et == "text" and isinstance(ev.get("data"), str):
                chunks.append(ev["data"])
            elif et == "end":
                sid = ev.get("sessionId") or ev.get("session_id") or sid
            elif et == "error":
                err = str(ev.get("message") or ev.get("data") or "error")
        if chunks or err:
            return BrainTurn(
                reply=("".join(chunks).strip() if chunks else (err or "")),
                session_id=str(sid) if sid else None,
                ok=err is None,
                error=err,
            )

    # Plain text fallback.
    return BrainTurn(reply=text, ok=True)


def _json_candidates(text: str) -> list[str]:
    """Yield likely JSON payloads from stdout (last object first)."""
    out: list[str] = []
    stripped = text.strip()
    if stripped.startswith("{"):
        out.append(stripped)
    # Last complete {...} block
    start = text.rfind("\n{")
    if start >= 0:
        out.append(text[start + 1 :].strip())
    elif text.rfind("{") > 0:
        out.append(text[text.rfind("{") :].strip())
    # Dedupe preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for c in out:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _actions_from_payload(data: dict) -> list[Action]:
    """Best-effort action extraction if the payload includes tool metadata."""
    actions: list[Action] = []
    raw = data.get("actions") or data.get("tools") or data.get("toolCalls")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("tool") or "tool")
            detail = str(
                item.get("detail")
                or item.get("input")
                or item.get("command")
                or item.get("path")
                or ""
            )
            if not isinstance(detail, str):
                detail = json.dumps(detail, default=str)[:200]
            actions.append(Action(name=name, detail=detail[:500]))
    return actions


__all__ = [
    "DEFAULT_GROK_SAFE_TOOLS",
    "GrokCliBrain",
    "parse_grok_output",
]
