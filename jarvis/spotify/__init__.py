"""Spotify voice control — playback, search, now-playing, volume (issue 09)."""

from jarvis.spotify.base import SpotifyControl, SpotifyError, SpotifyResult
from jarvis.spotify.controller import (
    SpotifyControllerImpl,
    SpotifyPlayer,
    build_spotify,
)
from jarvis.spotify.fake import FakeSpotifyControl, FakeSpotifyPlayer, sample_spotify
from jarvis.spotify.tokens import default_spotify_token_path, spotify_token_store

__all__ = [
    "FakeSpotifyControl",
    "FakeSpotifyPlayer",
    "SpotifyControl",
    "SpotifyControllerImpl",
    "SpotifyError",
    "SpotifyPlayer",
    "SpotifyResult",
    "build_spotify",
    "default_spotify_token_path",
    "sample_spotify",
    "spotify_token_store",
]
