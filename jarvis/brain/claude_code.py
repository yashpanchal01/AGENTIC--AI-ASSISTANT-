"""Claude Code headless brain adapter.

Spawns `claude -p` with stream-json output, safe-tier allowedTools, and
session resume so one long-lived conversation carries context across commands.
Supports ``cancel()`` so long-running tasks can be aborted (issue 10).
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.brain.stream_json import parse_stream_json_lines
from jarvis.config import DEFAULT_SAFE_TOOLS, JARVIS_SYSTEM_PROMPT, JarvisConfig
from jarvis.confirm import (
    confirmation_prompt,
    describe_risky_action,
    is_risky_request,
    is_secret_request,
    sanitize_user_command,
)
from jarvis.plain_replies import BRAIN_UNREACHABLE, looks_like_network_failure
from jarvis.types import BrainTurn


@dataclass
class ClaudeCodeBrain:
    """Real brain: Claude Code CLI behind the Brain protocol.

    Cancel policy: ``cancel()`` kills the Claude CLI process tree when possible.
    ``session_id`` is **retained** after cancel so the next turn can resume the
    same conversation (continuity over scrubbing a half-finished trajectory).
    Call ``reset_session()`` explicitly if a dirty resume is undesirable.
    """

    config: JarvisConfig = field(default_factory=JarvisConfig)
    session_id: str | None = None
    _claude_bin: str | None = field(default=None, init=False, repr=False)
    _proc: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    _proc_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _cancel: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )

    def cancel(self) -> None:
        """Abort the in-flight Claude CLI process tree (long-task cancel)."""
        self._cancel.set()
        with self._proc_lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            self._kill_proc(proc)

    def ask(self, command: str, *, confirmed: bool = False) -> BrainTurn:
        # Do not clear cancel before checking — an early cancel that races
        # worker start must still be honored. Clear after this ask exits.
        if self._cancel.is_set():
            self._cancel.clear()
            return BrainTurn(
                reply="Cancelled.",
                ok=False,
                error="cancelled",
                session_id=self.session_id,
            )

        # Local tier gate before the cloud brain (issue 06).
        # Spoof CONFIRMED: prefixes are stripped; only confirmed= authorizes.
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
                reply="I can't reach my brain — Claude CLI is not installed.",
                ok=False,
                error="claude_not_found",
                session_id=self.session_id,
            )

        with self._proc_lock:
            self._proc = proc

        # Drain pipes on a helper thread so a full stdout buffer cannot deadlock.
        io_box: dict[str, str | None] = {"stdout": None, "stderr": None}

        def _drain() -> None:
            out, err = proc.communicate()
            io_box["stdout"] = out
            io_box["stderr"] = err

        reader = threading.Thread(target=_drain, name="claude-io", daemon=True)
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
            lines = stdout.splitlines()
            turn = parse_stream_json_lines(lines)
            stderr_s = stderr.strip()
            combined_err = " ".join(
                p for p in (turn.error or "", turn.reply or "", stderr_s) if p
            )

            if turn.session_id:
                self.session_id = turn.session_id
            elif self.session_id and turn.session_id is None:
                turn = BrainTurn(
                    reply=turn.reply,
                    actions=turn.actions,
                    session_id=self.session_id,
                    denied=turn.denied,
                    needs_confirmation=turn.needs_confirmation,
                    proposed_action=turn.proposed_action,
                    ok=turn.ok,
                    error=turn.error,
                )

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
                # Prefer a short spoken result from stream-json; never read raw stderr aloud.
                if self._cancel.is_set():
                    return BrainTurn(
                        reply="Cancelled.",
                        ok=False,
                        error="cancelled",
                        session_id=session,
                    )
                reply = (turn.reply or "").strip()
                if not reply or "Traceback" in reply or len(reply) > 200:
                    reply = "Something went wrong talking to my brain."
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

            if session and turn.session_id != session:
                return BrainTurn(
                    reply=turn.reply,
                    actions=turn.actions,
                    session_id=session,
                    denied=turn.denied,
                    ok=turn.ok,
                    error=turn.error,
                )
            return turn
        finally:
            with self._proc_lock:
                if self._proc is proc:
                    self._proc = None
            # Ready for the next turn (whether cancelled, timed out, or ok).
            self._cancel.clear()

    @staticmethod
    def _kill_proc(proc: subprocess.Popen[str]) -> None:
        """Kill the CLI process and, on Windows, its child tree via taskkill /T."""
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
            except Exception:  # noqa: BLE001 — fall through to kill()
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
        bin_path = self._resolve_claude()
        tools = ",".join(self.config.safe_tools or DEFAULT_SAFE_TOOLS)
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
        args = [
            bin_path,
            "-p",
            command,
            "--output-format",
            "stream-json",
            "--verbose",
            "--allowedTools",
            tools,
            "--permission-mode",
            self.config.permission_mode,
            "--append-system-prompt",
            system,
        ]
        for folder in self.config.approved_folders:
            args.extend(["--add-dir", str(folder)])
        if self.session_id:
            args.extend(["--resume", self.session_id])
        model = self.config.claude_model
        if model and model != "default":
            args.extend(["--model", model])
        return args

    def _resolve_claude(self) -> str:
        if self._claude_bin:
            return self._claude_bin
        configured = self.config.claude_bin
        if Path(configured).is_file():
            self._claude_bin = configured
            return configured
        found = shutil.which(configured)
        if found:
            self._claude_bin = found
            return found
        # Fall back to configured name so subprocess raises FileNotFoundError.
        self._claude_bin = configured
        return configured

    def reset_session(self) -> None:
        """Start a fresh conversation (drop resume id)."""
        self.session_id = None
