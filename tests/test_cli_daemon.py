"""CLI --daemon / --front-door wiring with fakes."""

from __future__ import annotations

from jarvis.cli import main


def test_daemon_fake_wake_one_cycle(capsys) -> None:
    code = main(
        [
            "--fake",
            "--no-speak",
            "--no-hotkey",
            "--no-overlay",
            "--no-tray",
            "--no-audit",
            "--fake-wake",
            "--fake-stt",
            "open notepad",
            "--daemon",
            "--max-cycles",
            "1",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "front door" in captured.out.lower() or "You (voice)>" in captured.out
    assert "notepad" in captured.out.lower() or "Opened" in captured.out


def test_daemon_alias_front_door(capsys) -> None:
    code = main(
        [
            "--fake",
            "--no-speak",
            "--no-hotkey",
            "--no-overlay",
            "--no-tray",
            "--no-audit",
            "--fake-wake",
            "--fake-stt",
            "hello",
            "--front-door",
            "--max-cycles",
            "1",
        ]
    )
    assert code == 0
