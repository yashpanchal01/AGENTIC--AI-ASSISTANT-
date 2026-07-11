"""Claude Code headless brain adapter.

Spawns `claude -p` with stream-json output, safe-tier allowedTools, and
session resume so one long-lived conversation carries context across commands.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.brain.stream_json import parse_stream_json_lines
from jarvis.config import DEFAULT_SAFE_TOOLS, JARVIS_SYSTEM_PROMPT, JarvisConfig
from jarvis.types import BrainTurn


@dataclass
class ClaudeCodeBrain:
    """Real brain: Claude Code CLI behind the Brain protocol."""

    config: JarvisConfig = field(default_factory=JarvisConfig)
    session_id: str | None = None
    _claude_bin: str | None = field(default=None, init=False, repr=False)

    def ask(self, command: str) -> BrainTurn:
        args = self._build_args(command)
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(self.config.cwd),
                timeout=300,
                check=False,
            )
        except FileNotFoundError:
            return BrainTurn(
                reply="I can't reach my brain — Claude CLI is not installed.",
                ok=False,
                error="claude_not_found",
                session_id=self.session_id,
            )
        except subprocess.TimeoutExpired:
            return BrainTurn(
                reply="That took too long and I had to stop.",
                ok=False,
                error="timeout",
                session_id=self.session_id,
            )

        lines = (proc.stdout or "").splitlines()
        turn = parse_stream_json_lines(lines)
        stderr = (proc.stderr or "").strip()

        if turn.session_id:
            self.session_id = turn.session_id
        elif self.session_id and turn.session_id is None:
            turn = BrainTurn(
                reply=turn.reply,
                actions=turn.actions,
                session_id=self.session_id,
                denied=turn.denied,
                ok=turn.ok,
                error=turn.error,
            )

        session = self.session_id or turn.session_id

        if proc.returncode != 0:
            reply = turn.reply or (stderr[:300] if stderr else "The brain process failed.")
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
