"""Piper speaker: falls back cleanly when binary/model missing."""

from __future__ import annotations

from pathlib import Path

from jarvis.config import JarvisConfig
from jarvis.tts.piper import PiperSpeaker


def test_piper_falls_back_to_print_when_missing(capsys, tmp_path: Path) -> None:
    cfg = JarvisConfig(
        piper_exe=str(tmp_path / "no-such-piper"),
        piper_model=tmp_path / "missing.onnx",
    )
    speaker = PiperSpeaker(config=cfg, fallback_to_print=True)
    speaker.speak("Hello from JARVIS.")
    out = capsys.readouterr().out
    assert "Hello from JARVIS." in out


def test_piper_skips_empty_text(capsys) -> None:
    speaker = PiperSpeaker(fallback_to_print=True)
    speaker.speak("  ")
    assert capsys.readouterr().out == ""
