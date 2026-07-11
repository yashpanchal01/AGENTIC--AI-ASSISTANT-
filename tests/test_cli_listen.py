"""CLI --listen / --fake-stt wiring (no real mic or whisper)."""

from __future__ import annotations

from jarvis.cli import main


def test_fake_stt_feeds_handle_command(capsys) -> None:
    code = main(
        ["--fake", "--no-speak", "--fake-stt", "open notepad"]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "You (voice)>" in captured.out
    assert "notepad" in captured.out.lower() or "Opened" in captured.out


def test_listen_and_once_are_mutually_exclusive(capsys) -> None:
    code = main(["--fake", "--once", "hi", "--listen"])
    assert code == 2
