"""Piper local TTS speaker.

Shells out to the `piper` binary with a configured ONNX voice model.
Falls back to printing the reply when Piper is unavailable (so the
headless loop still works for development without audio deps).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.config import JarvisConfig


@dataclass
class PiperSpeaker:
    """Speak text via Piper. Records last synthesis path for debugging."""

    config: JarvisConfig = field(default_factory=JarvisConfig)
    fallback_to_print: bool = True
    last_wav: Path | None = field(default=None, init=False)
    _piper_bin: str | None = field(default=None, init=False, repr=False)

    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return

        model = self.config.piper_model
        exe = self._resolve_piper()
        if not exe or not model or not Path(model).exists():
            if self.fallback_to_print:
                print(f"[jarvis speak] {text}", flush=True)
            return

        out_dir = Path.home() / ".jarvis" / "tts"
        out_dir.mkdir(parents=True, exist_ok=True)
        wav_path = out_dir / f"reply-{uuid.uuid4().hex[:10]}.wav"

        try:
            self._synthesize(exe, Path(model), text, wav_path)
            self.last_wav = wav_path
            self._play_wav(wav_path)
        except (OSError, subprocess.SubprocessError, wave.Error) as exc:
            if self.fallback_to_print:
                print(f"[jarvis speak-fallback] {text}  ({exc})", flush=True)
            try:
                wav_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _synthesize(
        self, exe: str, model: Path, text: str, wav_path: Path
    ) -> None:
        # piper reads text on stdin, writes raw or wav depending on flags.
        # Prefer --output_file for a .wav we can play portably.
        cmd = [
            exe,
            "--model",
            str(model),
            "--output_file",
            str(wav_path),
        ]
        subprocess.run(
            cmd,
            input=text,
            text=True,
            capture_output=True,
            check=True,
            timeout=60,
        )

    def _resolve_piper(self) -> str | None:
        if self._piper_bin:
            return self._piper_bin
        configured = self.config.piper_exe
        if Path(configured).is_file():
            self._piper_bin = configured
            return configured
        found = shutil.which(configured)
        if found:
            self._piper_bin = found
            return found
        # Common local install locations on this machine.
        candidates = [
            Path.home() / ".local" / "piper" / "piper" / "piper.exe",
            Path.home() / ".local" / "bin" / "piper.exe",
            Path.home() / ".local" / "bin" / "piper",
            Path("C:/piper/piper.exe"),
            Path.home() / "piper" / "piper.exe",
        ]
        for c in candidates:
            if c.is_file():
                self._piper_bin = str(c)
                return self._piper_bin
        return None

    def _play_wav(self, wav_path: Path) -> None:
        """Play a WAV file on Windows without extra deps when possible."""
        if sys.platform == "win32":
            try:
                import winsound

                winsound.PlaySound(
                    str(wav_path),
                    winsound.SND_FILENAME | winsound.SND_NODEFAULT,
                )
                return
            except Exception:
                pass
        # Fallback: open with default app (non-blocking-ish).
        if sys.platform == "win32":
            subprocess.Popen(
                ["cmd", "/c", "start", "/min", "", str(wav_path)],
                shell=False,
            )
        elif sys.platform == "darwin":
            subprocess.run(["afplay", str(wav_path)], check=False)
        else:
            subprocess.run(["aplay", str(wav_path)], check=False)
