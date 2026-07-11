"""Text-to-speech adapters."""

from jarvis.tts.base import Speaker
from jarvis.tts.fake import FakeSpeaker
from jarvis.tts.piper import PiperSpeaker

__all__ = ["FakeSpeaker", "PiperSpeaker", "Speaker"]
