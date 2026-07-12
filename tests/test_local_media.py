"""Local media: find + open + optional true-FS / half-snap."""

from __future__ import annotations

import time
from pathlib import Path

from jarvis.brain.fake import FakeBrain
from jarvis.core import handle_command
from jarvis.media.handler import LocalMediaHandler, find_media, score_match
from jarvis.media.intents import MediaIntentKind, classify, extract_query
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import BrainTurn


def test_classify_find_in_downloads_is_local() -> None:
    intent = classify(
        "go to my Downloads folder, find Project Hail Mary, and play it"
    )
    assert intent.kind is MediaIntentKind.PLAY_LOCAL
    assert "hail" in intent.query.lower()
    assert intent.fullscreen is False
    assert intent.snap is None


def test_classify_left_half_snap() -> None:
    intent = classify(
        "play hail marry from downloads, keep it on the left half of the screen"
    )
    assert intent.kind is MediaIntentKind.PLAY_LOCAL
    assert intent.snap == "left"
    assert "hail" in intent.query.lower()
    assert "left" not in intent.query.lower()
    assert "screen" not in intent.query.lower()


def test_classify_fullscreen_flag_only_when_asked() -> None:
    intent = classify(
        "find Project Hail Mary in Downloads and play it fullscreen"
    )
    assert intent.kind is MediaIntentKind.PLAY_LOCAL
    assert intent.fullscreen is True
    assert "fullscreen" not in intent.query.lower()


def test_classify_music_stays_unrelated() -> None:
    assert classify("play bohemian rhapsody by queen").kind is MediaIntentKind.UNRELATED
    assert classify("play the playlist chill vibes").kind is MediaIntentKind.UNRELATED


def test_open_brave_is_not_media() -> None:
    """Regression: 'open brave' must not soft-match trombone-grave.mp3."""
    assert classify("open brave").kind is MediaIntentKind.UNRELATED
    assert classify("open chrome").kind is MediaIntentKind.UNRELATED
    assert classify("launch notepad").kind is MediaIntentKind.UNRELATED


def test_brave_does_not_match_grave_file(tmp_path: Path) -> None:
    bad = tmp_path / "trombone-grave-4-97788.mp3"
    bad.write_bytes(b"x")
    assert find_media("brave", [tmp_path]) is None
    assert score_match("brave", bad) == 0.0


def test_extract_query_strips_chrome() -> None:
    q = extract_query("Find Project Hail Mary mp4 in my Downloads folder and play it")
    assert "hail" in q.lower()
    assert "downloads" not in q.lower()


def test_find_media_prefers_finished_over_pending(tmp_path: Path) -> None:
    (tmp_path / ".pending-123-Project Hail Mary (2026).mp4").write_bytes(b"x")
    good = tmp_path / "Project Hail Mary (2026).mp4"
    good.write_bytes(b"y")
    assert find_media("Project Hail Mary", [tmp_path]) == good


def test_fuzzy_match_typo_in_title(tmp_path: Path) -> None:
    good = tmp_path / "Project Hail Mary (2026).mp4"
    good.write_bytes(b"y")
    assert find_media("Prject Hail Marry", [tmp_path]) == good


def test_handle_command_opens_local_file_not_brain(tmp_path: Path) -> None:
    movie = tmp_path / "Project Hail Mary (2026).mp4"
    movie.write_bytes(b"video")
    opened: list[Path] = []

    media = LocalMediaHandler(roots=(tmp_path,), open_fn=opened.append)
    result = handle_command(
        "go to my Downloads folder, find Project Hail Mary, and play it",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        media=media,
    )
    assert result.ok is True
    assert opened == [movie]
    assert any(a.name == "local_media_open" for a in result.actions)


def test_snap_left_requests_layout(tmp_path: Path) -> None:
    movie = tmp_path / "Project Hail Mary (2026).mp4"
    movie.write_bytes(b"video")
    opened: list[Path] = []
    snaps: list[str] = []

    media = LocalMediaHandler(
        roots=(tmp_path,),
        open_fn=opened.append,
        snap_fn=lambda side: snaps.append(side),
        layout_delay_s=0.0,
    )
    result = handle_command(
        "play hail marry from downloads, keep it on the left half of the screen",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        media=media,
    )
    assert result.ok
    assert any(a.name == "local_media_snap" for a in result.actions)
    assert "left" in result.reply.lower()
    time.sleep(0.15)
    assert snaps == ["left"]


def test_fullscreen_only_when_requested(tmp_path: Path) -> None:
    movie = tmp_path / "Project Hail Mary (2026).mp4"
    movie.write_bytes(b"video")
    opened: list[Path] = []
    fs_calls: list[str] = []

    media = LocalMediaHandler(
        roots=(tmp_path,),
        open_fn=opened.append,
        fullscreen_fn=lambda: fs_calls.append("fs") or "ok",
        layout_delay_s=0.0,
    )
    r1 = handle_command(
        "play Project Hail Mary from downloads",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        media=media,
    )
    assert not any(a.name == "local_media_fullscreen" for a in r1.actions)

    r2 = handle_command(
        "play Project Hail Mary from downloads in fullscreen",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        media=media,
    )
    assert any(a.name == "local_media_fullscreen" for a in r2.actions)
    time.sleep(0.15)
    assert fs_calls


def test_play_if_match_falls_through_when_missing(tmp_path: Path) -> None:
    media = LocalMediaHandler(roots=(tmp_path,), open_fn=lambda p: None)
    brain = FakeBrain(script=[BrainTurn(reply="brain got it", actions=())])
    result = handle_command(
        "play totally missing xyzzy",
        brain=brain,
        speaker=FakeSpeaker(),
        media=media,
    )
    assert result.reply == "brain got it"


def test_score_match_requires_tokens() -> None:
    p = Path("Project Hail Mary (2026).mp4")
    assert score_match("Project Hail Mary", p) >= 0.9
    assert score_match("Dhurandhar", p) < 0.5
