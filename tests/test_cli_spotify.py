"""CLI wiring for Spotify voice control (issue 09)."""

from __future__ import annotations

from jarvis.cli import main


def test_fake_once_pause_the_music(capsys) -> None:
    code = main(["--fake", "--no-speak", "--once", "pause the music"])
    captured = capsys.readouterr()
    assert code == 0
    assert "paused" in captured.out.lower()
    assert "spotify_pause" in captured.out


def test_fake_once_play_named_song(capsys) -> None:
    code = main(
        ["--fake", "--no-speak", "--once", "play bohemian rhapsody by queen"]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "bohemian rhapsody" in captured.out.lower()
    assert "spotify_play" in captured.out


def test_fake_once_whats_playing(capsys) -> None:
    code = main(["--fake", "--no-speak", "--once", "what's playing?"])
    captured = capsys.readouterr()
    assert code == 0
    assert "spotify_now_playing" in captured.out


def test_no_spotify_falls_through_to_brain(capsys) -> None:
    code = main(
        ["--fake", "--no-spotify", "--no-speak", "--once", "pause the music"]
    )
    captured = capsys.readouterr()
    assert code == 0
    # Without spotify, FakeBrain's generic path answers (no spotify actions).
    assert "spotify_pause" not in captured.out


def test_open_spotify_is_an_app_launch_not_playback(capsys) -> None:
    # Hermetic app ops (conftest): nothing "running" → smart-open launches.
    # Previously this hit the real Win32 window list and flip-flopped between
    # app_focus/app_launch depending on whether Spotify was open on the machine.
    code = main(["--fake", "--no-speak", "--once", "open spotify"])
    captured = capsys.readouterr()
    assert code == 0
    assert "app_launch" in captured.out
    assert "spotify_play" not in captured.out


def test_spotify_login_without_client_id_fails_cleanly(capsys, monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_SPOTIFY_CLIENT_ID", raising=False)
    code = main(["--spotify-login"])
    captured = capsys.readouterr()
    assert code == 2
    assert "spotify-setup" in captured.err.lower()
