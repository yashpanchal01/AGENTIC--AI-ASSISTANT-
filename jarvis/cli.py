"""Terminal front door for the headless core loop (no overlay).

Usage:
  py -3.13 -m jarvis                  # interactive REPL
  py -3.13 -m jarvis --once "open notepad"
  py -3.13 -m jarvis --fake --once "what's 2+2"
  py -3.13 -m jarvis --no-speak --once "list files in downloads"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jarvis.brain.claude_code import ClaudeCodeBrain
from jarvis.brain.fake import FakeBrain
from jarvis.config import JarvisConfig
from jarvis.core import handle_command
from jarvis.tts.fake import FakeSpeaker
from jarvis.tts.piper import PiperSpeaker


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jarvis",
        description="JARVIS headless core loop — text → brain → act → Piper",
    )
    p.add_argument(
        "--once",
        metavar="COMMAND",
        help="Run a single command and exit",
    )
    p.add_argument(
        "--fake",
        action="store_true",
        help="Use the in-process FakeBrain (no Claude CLI)",
    )
    p.add_argument(
        "--no-speak",
        action="store_true",
        help="Do not run Piper; print replies only",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Claude model (default: sonnet, or JARVIS_MODEL)",
    )
    p.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="Working directory for the brain",
    )
    return p


def make_brain(config: JarvisConfig, *, fake: bool):
    if fake:
        return FakeBrain()
    return ClaudeCodeBrain(config=config)


def make_speaker(config: JarvisConfig, *, no_speak: bool):
    if no_speak or not config.speak:
        return FakeSpeaker()
    return PiperSpeaker(config=config, fallback_to_print=True)


def run_once(command: str, *, brain, speaker) -> int:
    result = handle_command(command, brain=brain, speaker=speaker)
    _print_result(result)
    return 0 if result.ok else 1


def run_repl(*, brain, speaker) -> int:
    print("JARVIS headless core loop  (type a command, :n new session, :q quit)")
    if isinstance(brain, ClaudeCodeBrain):
        print(f"  brain: Claude Code  model={brain.config.claude_model}")
    else:
        print("  brain: FakeBrain")
    print(f"  speaker: {type(speaker).__name__}")
    print()

    while True:
        try:
            line = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        if line in (":q", ":quit", "quit", "exit"):
            break
        if line in (":n", ":new"):
            if hasattr(brain, "reset_session"):
                brain.reset_session()
            print("(new conversation)")
            continue

        result = handle_command(line, brain=brain, speaker=speaker)
        _print_result(result)

    print("bye")
    return 0


def _print_result(result) -> None:
    flags = []
    if result.denied:
        flags.append("denied")
    if not result.ok:
        flags.append("failed")
    flag_s = f"  [{', '.join(flags)}]" if flags else ""
    print(f"JARVIS> {result.reply}{flag_s}")
    if result.actions:
        names = " → ".join(
            f"{a.name}({a.detail})" if a.detail else a.name for a in result.actions
        )
        print(f"  actions: {names}")
    if result.session_id:
        sid = result.session_id
        shown = sid if len(sid) <= 12 else sid[:12] + "…"
        print(f"  session: {shown}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = JarvisConfig.from_env()
    if args.model:
        config.claude_model = args.model
    if args.cwd:
        config.cwd = args.cwd
    if args.no_speak:
        config.speak = False

    brain = make_brain(config, fake=args.fake)
    speaker = make_speaker(config, no_speak=args.no_speak)

    if args.once is not None:
        return run_once(args.once, brain=brain, speaker=speaker)
    return run_repl(brain=brain, speaker=speaker)


if __name__ == "__main__":
    sys.exit(main())
