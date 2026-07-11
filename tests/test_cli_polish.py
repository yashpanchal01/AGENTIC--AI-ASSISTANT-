"""CLI wiring for autostart / settings path (issue 11)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from jarvis.cli import main


def test_install_autostart_cli(capsys) -> None:
    with mock.patch(
        "jarvis.autostart.install_autostart",
        return_value="python -m jarvis --daemon",
    ) as inst:
        code = main(["--install-autostart", "--no-audit"])
        assert code == 0
        inst.assert_called_once()
    out = capsys.readouterr().out
    assert "autostart installed" in out.lower()
    assert "reboot" in out.lower()


def test_uninstall_autostart_cli(capsys) -> None:
    with mock.patch("jarvis.autostart.uninstall_autostart", return_value=True) as un:
        code = main(["--uninstall-autostart", "--no-audit"])
        assert code == 0
        un.assert_called_once()
    assert "removed" in capsys.readouterr().out.lower()


def test_daemon_with_settings_file(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hotkey": "ctrl+alt+x"}), encoding="utf-8")
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
            "--settings",
            str(settings),
        ]
    )
    assert code == 0


def test_daemon_still_works_no_tray_no_overlay(capsys) -> None:
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
            "--daemon",
            "--max-cycles",
            "1",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out.lower()
    assert "front door" in out or "you (voice)" in out
