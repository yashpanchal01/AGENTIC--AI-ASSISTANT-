"""Behavioral tests for Spotify voice control (issue 09, user stories 26–28).

Seams (PRD): handle_command(transcript, spotify=...) → reply + actions +
spoken. The Spotify Web API is always faked — no network, no audio.
"""

from __future__ import annotations

from jarvis.brain.fake import FakeBrain
from jarvis.core import handle_command
from jarvis.spotify.controller import SpotifyControllerImpl
from jarvis.spotify.fake import FakeSpotifyPlayer, sample_spotify
from jarvis.spotify.tokens import TokenStore, default_spotify_token_path, memory_notes_dir
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import Action, BrainTurn


class OfflineConnectivity:
    def is_online(self) -> bool:
        return False


# --- play by song / artist / playlist name (story 27) -----------------------


def test_play_named_song_by_voice() -> None:
    brain = FakeBrain(script=[])  # brain must not be consulted
    speaker = FakeSpeaker()
    spotify = sample_spotify()

    result = handle_command(
        "play bohemian rhapsody by queen",
        brain=brain,
        speaker=speaker,
        spotify=spotify,
    )

    assert result.ok is True
    assert "bohemian rhapsody" in result.reply.lower()
    assert "queen" in result.reply.lower()
    assert any(a.name == "spotify_play" for a in result.actions)
    assert speaker.spoken == [result.reply]
    assert brain._history == []


def test_play_artist_by_name() -> None:
    speaker = FakeSpeaker()
    spotify = sample_spotify()

    result = handle_command(
        "play something by daft punk",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=spotify,
    )

    assert result.ok is True
    assert "daft punk" in result.reply.lower()
    assert any(a.name == "spotify_play" for a in result.actions)
    assert speaker.spoken == [result.reply]


def test_play_playlist_by_name() -> None:
    speaker = FakeSpeaker()
    spotify = sample_spotify()

    result = handle_command(
        "play the playlist chill vibes",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=spotify,
    )

    assert result.ok is True
    assert "playlist" in result.reply.lower()
    assert "chill vibes" in result.reply.lower()
    assert any(a.name == "spotify_play" for a in result.actions)


def test_play_some_lofi_just_works() -> None:
    """PRD story 27: 'Jarvis, play some lo-fi' just works."""
    speaker = FakeSpeaker()
    spotify = sample_spotify()

    result = handle_command(
        "play some lo-fi",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=spotify,
    )

    assert result.ok is True
    assert "lo-fi" in result.reply.lower()
    assert speaker.spoken == [result.reply]


def test_play_unknown_song_spoken_plainly() -> None:
    speaker = FakeSpeaker()
    spotify = sample_spotify()

    result = handle_command(
        "play the song zanzibar dreams",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=spotify,
    )

    assert "couldn't find" in result.reply.lower()
    assert speaker.spoken == [result.reply]


# --- pause / resume / skip (story 26) ---------------------------------------


def test_pause_the_music() -> None:
    player = FakeSpotifyPlayer()
    speaker = FakeSpeaker()
    spotify = sample_spotify(player=player)

    result = handle_command(
        "pause the music",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=spotify,
    )

    assert result.ok is True
    assert "paused" in result.reply.lower()
    assert player.playing is False
    assert any(a.name == "spotify_pause" for a in result.actions)
    assert speaker.spoken == [result.reply]


def test_stop_the_music_pauses() -> None:
    """'stop the music' is a pause — never swallowed by long-task cancel."""
    player = FakeSpotifyPlayer()
    result = handle_command(
        "stop the music",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        spotify=sample_spotify(player=player),
    )
    assert player.playing is False
    assert any(a.name == "spotify_pause" for a in result.actions)


def test_resume_the_music() -> None:
    player = FakeSpotifyPlayer(playing=False)
    speaker = FakeSpeaker()

    result = handle_command(
        "resume the music",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=sample_spotify(player=player),
    )

    assert result.ok is True
    assert player.playing is True
    assert any(a.name == "spotify_resume" for a in result.actions)


def test_bare_play_and_generic_play_music_resume() -> None:
    for cmd in ("play", "play some music"):
        player = FakeSpotifyPlayer(playing=False)
        result = handle_command(
            cmd,
            brain=FakeBrain(script=[]),
            speaker=FakeSpeaker(),
            spotify=sample_spotify(player=player),
        )
        assert player.playing is True, cmd
        assert any(a.name == "spotify_resume" for a in result.actions), cmd


def test_skip_this_song() -> None:
    player = FakeSpotifyPlayer()
    speaker = FakeSpeaker()

    result = handle_command(
        "skip this song",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=sample_spotify(player=player),
    )

    assert result.ok is True
    assert "skipped" in result.reply.lower()
    assert any(a.name == "spotify_next" for a in result.actions)
    assert "next" in player.calls


def test_next_song_skips_too() -> None:
    player = FakeSpotifyPlayer()
    result = handle_command(
        "next song",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        spotify=sample_spotify(player=player),
    )
    assert any(a.name == "spotify_next" for a in result.actions)


# --- now-playing + volume (story 28) ----------------------------------------


def test_whats_playing_spoken() -> None:
    speaker = FakeSpeaker()
    spotify = sample_spotify(player=FakeSpotifyPlayer(track="Midnight City", artist="M83"))

    result = handle_command(
        "what's playing?",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=spotify,
    )

    assert result.ok is True
    assert "midnight city" in result.reply.lower()
    assert "m83" in result.reply.lower()
    assert any(a.name == "spotify_now_playing" for a in result.actions)
    assert speaker.spoken == [result.reply]


def test_volume_up_and_down_by_voice() -> None:
    player = FakeSpotifyPlayer(volume=50)
    spotify = sample_spotify(player=player)

    up = handle_command(
        "turn it up",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        spotify=spotify,
    )
    assert player.volume == 60
    assert any(a.name == "spotify_volume" for a in up.actions)

    down = handle_command(
        "quieter please",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        spotify=spotify,
    )
    assert player.volume == 50
    assert any(a.name == "spotify_volume" for a in down.actions)


def test_set_volume_to_number() -> None:
    player = FakeSpotifyPlayer(volume=50)
    speaker = FakeSpeaker()

    result = handle_command(
        "set the volume to 30",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=sample_spotify(player=player),
    )

    assert player.volume == 30
    assert "30" in result.reply
    assert speaker.spoken == [result.reply]


# --- failures spoken in plain language (acceptance criterion) ----------------


def test_no_active_device_is_spoken_plainly() -> None:
    player = FakeSpotifyPlayer(no_active_device=True)
    speaker = FakeSpeaker()

    result = handle_command(
        "pause the music",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=sample_spotify(player=player),
    )

    assert result.ok is False
    assert result.error == "spotify_error"
    assert "spotify" in result.reply.lower()
    assert "device" in result.reply.lower()
    assert "traceback" not in result.reply.lower()
    assert speaker.spoken == [result.reply]


def test_not_configured_points_to_setup_doc() -> None:
    """No client ID yet → short spoken pointer to the setup doc, not an error."""
    speaker = FakeSpeaker()
    spotify = sample_spotify(configured=False)

    result = handle_command(
        "play some lo-fi",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=spotify,
    )

    assert result.ok is False
    assert result.error == "not_configured"
    assert "spotify-setup" in result.reply.lower()
    assert speaker.spoken == [result.reply]


def test_not_signed_in_prompts_login() -> None:
    speaker = FakeSpeaker()
    spotify = sample_spotify(signed_in=False)

    result = handle_command(
        "pause the music",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=spotify,
    )

    assert result.ok is False
    assert result.error == "not_signed_in"
    assert "--spotify-login" in result.reply
    assert speaker.spoken == [result.reply]


def test_offline_live_spotify_spoken_plainly() -> None:
    """Signed-in live control needs the network → plain offline reply."""
    speaker = FakeSpeaker()
    live_like = SpotifyControllerImpl(
        player=FakeSpotifyPlayer(), configured=True, signed_in=True, works_offline=False
    )

    result = handle_command(
        "pause the music",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=live_like,
        connectivity=OfflineConnectivity(),
    )

    assert result.ok is False
    assert result.error == "spotify_unreachable"
    assert "internet" in result.reply.lower() or "reach" in result.reply.lower()
    assert speaker.spoken == [result.reply]


def test_offline_setup_pointer_still_answers() -> None:
    """Not-configured reply is local — it must work even offline."""
    speaker = FakeSpeaker()
    spotify = SpotifyControllerImpl(configured=False, works_offline=False)

    result = handle_command(
        "play some lo-fi",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=spotify,
        connectivity=OfflineConnectivity(),
    )

    assert result.error == "not_configured"
    assert "spotify-setup" in result.reply.lower()


# --- routing ------------------------------------------------------------------


def test_open_spotify_still_launches_the_app_via_brain() -> None:
    """PRD story 14: 'open Spotify' is an app launch, not a playback command."""
    brain = FakeBrain(
        script=[
            BrainTurn(
                reply="Opened Spotify.",
                actions=(Action(name="launch_app", detail="Spotify"),),
            )
        ]
    )
    speaker = FakeSpeaker()

    result = handle_command(
        "open spotify",
        brain=brain,
        speaker=speaker,
        spotify=sample_spotify(),
    )

    assert result.reply == "Opened Spotify."
    assert result.actions[0].name == "launch_app"


def test_non_music_commands_still_use_brain() -> None:
    brain = FakeBrain(
        script=[
            BrainTurn(
                reply="Opened Notepad.",
                actions=(Action(name="launch_app", detail="Notepad"),),
            )
        ]
    )
    result = handle_command(
        "open notepad",
        brain=brain,
        speaker=FakeSpeaker(),
        spotify=sample_spotify(),
    )
    assert result.actions[0].name == "launch_app"


def test_google_and_spotify_coexist() -> None:
    from jarvis.google.fake import sample_workspace

    google = sample_workspace()
    spotify = sample_spotify()

    mail = handle_command(
        "any new email?",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        google=google,
        spotify=spotify,
    )
    assert any(a.name == "gmail_unread" for a in mail.actions)

    music = handle_command(
        "pause the music",
        brain=FakeBrain(script=[]),
        speaker=FakeSpeaker(),
        google=google,
        spotify=spotify,
    )
    assert any(a.name == "spotify_pause" for a in music.actions)


def test_without_spotify_arg_brain_handles_as_before() -> None:
    result = handle_command(
        "play bohemian rhapsody",
        brain=FakeBrain(),
        speaker=FakeSpeaker(),
    )
    # FakeBrain rule-based fallback answers; no spotify actions exist.
    assert all(not a.name.startswith("spotify_") for a in result.actions)


# --- token safety ---------------------------------------------------------------


def test_default_spotify_token_path_is_not_under_memory_notes() -> None:
    token = default_spotify_token_path()
    mem = memory_notes_dir()
    assert TokenStore.is_safe_path(token, memory_notes_root=mem)


def test_spoken_reply_never_includes_token_material() -> None:
    speaker = FakeSpeaker()
    result = handle_command(
        "what's playing?",
        brain=FakeBrain(script=[]),
        speaker=speaker,
        spotify=sample_spotify(),
    )
    assert "token" not in result.reply.lower()
    assert "refresh" not in result.reply.lower()
