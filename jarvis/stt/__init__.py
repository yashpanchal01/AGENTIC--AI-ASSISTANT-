"""Speech-to-text: local faster-whisper + dictionary hotwords."""

from jarvis.stt.base import Transcriber
from jarvis.stt.dictionary import fix_terms, load_dictionary
from jarvis.stt.fake import FakeTranscriber

__all__ = [
    "Transcriber",
    "FakeTranscriber",
    "fix_terms",
    "load_dictionary",
]
