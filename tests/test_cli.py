"""CLI wiring: --fake --once exercises the same handle_command path."""

from __future__ import annotations

from jarvis.cli import main


def test_once_fake_prints_reply(capsys) -> None:
    code = main(["--fake", "--no-speak", "--once", "open notepad"])
    captured = capsys.readouterr()
    assert code == 0
    assert "Opened" in captured.out or "notepad" in captured.out.lower()


def test_once_empty_returns_nonzero(capsys) -> None:
    code = main(["--fake", "--no-speak", "--once", "   "])
    assert code == 1
