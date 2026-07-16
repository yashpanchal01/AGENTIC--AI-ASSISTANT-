"""ClaudeCodeBrain builds the prototype-validated CLI invocation shape."""

from __future__ import annotations

from pathlib import Path

from jarvis.brain.claude_code import ClaudeCodeBrain
from jarvis.config import JarvisConfig


def test_build_args_includes_stream_json_and_safe_tools() -> None:
    approved = (Path.home() / "Documents",)
    cfg = JarvisConfig(
        claude_bin="claude",
        claude_model="sonnet",
        permission_mode="acceptEdits",
        safe_tools=("Bash", "Read", "Write"),
        approved_folders=approved,
        cwd=Path.cwd(),
    )
    brain = ClaudeCodeBrain(config=cfg)
    args = brain._build_args("open notepad")

    assert args[0] in ("claude",) or args[0].endswith("claude.exe") or "claude" in args[0]
    assert "-p" in args
    assert args[args.index("-p") + 1] == "open notepad"
    assert "--output-format" in args
    assert "stream-json" in args
    assert "--verbose" in args
    assert "--allowedTools" in args
    tools = args[args.index("--allowedTools") + 1]
    assert "Bash" in tools and "Read" in tools
    assert "--permission-mode" in args
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"
    assert "--append-system-prompt" in args
    prompt = args[args.index("--append-system-prompt") + 1]
    assert "JARVIS" in prompt
    assert "--add-dir" in args
    assert str(approved[0]) in args
    assert "--model" in args
    assert args[args.index("--model") + 1] == "sonnet"
    assert "--resume" not in args


def test_build_args_resumes_session() -> None:
    brain = ClaudeCodeBrain(config=JarvisConfig())
    brain.session_id = "sess-xyz"
    args = brain._build_args("actually close it")
    assert "--resume" in args
    assert args[args.index("--resume") + 1] == "sess-xyz"


def test_reset_session_clears_resume() -> None:
    brain = ClaudeCodeBrain()
    brain.session_id = "sess-1"
    brain.reset_session()
    assert brain.session_id is None
    assert "--resume" not in brain._build_args("hello")


def test_no_bridge_means_no_mcp_registration() -> None:
    args = ClaudeCodeBrain(config=JarvisConfig())._build_args("hello")
    assert "--mcp-config" not in args
    assert not any("mcp__jarvis__" in a for a in args)


def test_build_args_registers_mcp_tool_bridge() -> None:
    import json

    from jarvis.brain.mcp_bridge import JarvisToolBridge, allowed_tool_ids

    bridge = JarvisToolBridge()
    brain = ClaudeCodeBrain(config=JarvisConfig(), tool_bridge=bridge)
    try:
        args = brain._build_args("open spotify and play the next track")

        # The in-process HTTP MCP server is registered by URL.
        assert "--mcp-config" in args
        cfg = json.loads(args[args.index("--mcp-config") + 1])
        server = cfg["mcpServers"]["jarvis"]
        assert server["type"] == "http"
        assert server["url"].startswith("http://127.0.0.1:")
        assert server["url"].endswith("/mcp")

        # All bridge tools are allow-listed alongside the safe read tools.
        tools = args[args.index("--allowedTools") + 1]
        for tool_id in allowed_tool_ids():
            assert tool_id in tools
        assert "Read" in tools  # safe read tools still present
        # The CLI's own Bash stays OFF (issue 21): raw shell would bypass the
        # confirm gate — shell goes through the bridge's run_command tool.
        assert "Bash" not in tools.split(",")

        # The brain is told to prefer the JARVIS tools over shell.
        prompt = args[args.index("--append-system-prompt") + 1]
        assert "JARVIS" in prompt
        assert "prefer" in prompt.lower()
        assert "google_read" in prompt
    finally:
        bridge.stop()
