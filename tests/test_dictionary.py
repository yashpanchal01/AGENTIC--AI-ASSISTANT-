"""Dictionary hotwords and post-transcription term fixes."""

from __future__ import annotations

from pathlib import Path

from jarvis.stt.dictionary import (
    DEFAULT_DICTIONARY,
    fix_terms,
    hotwords_string,
    load_dictionary,
)


def test_fix_terms_recovers_claude_code_mishears() -> None:
    assert fix_terms("open broadcourt please") == "open Claude Code please"
    assert fix_terms("run claw code") == "run Claude Code"
    assert fix_terms("check get hub") == "check GitHub"


def test_fix_terms_normalizes_jarvis() -> None:
    assert "Jarvis" in fix_terms("hey jarves open notepad")


def test_load_dictionary_seeds_file(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    terms = load_dictionary(path)
    assert path.exists()
    assert "Claude Code" in terms
    assert "Jarvis" in terms
    # Edits win on next load
    path.write_text("# comment\nMyProject\n", encoding="utf-8")
    assert load_dictionary(path) == ["MyProject"]


def test_hotwords_string_joins_terms(tmp_path: Path) -> None:
    path = tmp_path / "d.txt"
    path.write_text("Alpha\nBeta\n", encoding="utf-8")
    assert hotwords_string(path) == "Alpha Beta"


def test_default_dictionary_includes_assistant_terms() -> None:
    assert "Jarvis" in DEFAULT_DICTIONARY
    assert "Piper" in DEFAULT_DICTIONARY
