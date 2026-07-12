"""In-process fake Spotify player for automated tests and demos — no network."""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.spotify.base import SpotifyError
from jarvis.spotify.controller import SpotifyControllerImpl


@dataclass
class FakeSpotifyPlayer:
    """Scriptable player with a tiny sample catalog and playback state."""

    playing: bool = True
    track: str = "Midnight City"
    artist: str = "M83"
    volume: int = 50
    # Known tracks: lookup key → (title, artist)
    tracks: dict[str, tuple[str, str]] = field(
        default_factory=lambda: {
            "bohemian rhapsody": ("Bohemian Rhapsody", "Queen"),
            "lo-fi": ("Lo-Fi Study Beats", "Chillhop Radio"),
            "lofi": ("Lo-Fi Study Beats", "Chillhop Radio"),
            "midnight city": ("Midnight City", "M83"),
        }
    )
    playlists: dict[str, str] = field(
        default_factory=lambda: {
            "chill vibes": "Chill Vibes",
            "focus flow": "Focus Flow",
        }
    )
    artists: dict[str, str] = field(
        default_factory=lambda: {
            "daft punk": "Daft Punk",
            "queen": "Queen",
        }
    )
    # Simulate the live failure modes (raise SpotifyError with plain text).
    no_active_device: bool = False
    calls: list[str] = field(default_factory=list)

    def _check_device(self) -> None:
        if self.no_active_device:
            raise SpotifyError(
                "Spotify isn't active on any device — open the Spotify app, "
                "press play once, and try again."
            )

    def play(self, query: str, kind: str = "any") -> str:
        self.calls.append(f"play:{kind}:{query}")
        self._check_device()
        q = (query or "").strip().lower()
        if not q:
            return self.resume()
        if kind in ("playlist", "any"):
            for key, name in self.playlists.items():
                if key in q or q in key:
                    self.playing = True
                    self.track, self.artist = name, ""
                    return f"Playing the playlist {name}."
            if kind == "playlist":
                return f"I couldn't find {query} on Spotify."
        if kind == "artist":
            for key, name in self.artists.items():
                if key in q or q in key:
                    self.playing = True
                    self.track, self.artist = f"top songs by {name}", name
                    return f"Playing music by {name}."
            return f"I couldn't find {query} on Spotify."
        for key, (title, artist) in self.tracks.items():
            if key in q or q in key:
                self.playing = True
                self.track, self.artist = title, artist
                return f"Playing {title} by {artist}."
        return f"I couldn't find {query} on Spotify."

    def pause(self) -> str:
        self.calls.append("pause")
        self._check_device()
        self.playing = False
        return "Paused."

    def resume(self) -> str:
        self.calls.append("resume")
        self._check_device()
        self.playing = True
        return "Resuming."

    def next_track(self) -> str:
        self.calls.append("next")
        self._check_device()
        self.playing = True
        return "Skipped."

    def now_playing(self) -> str:
        self.calls.append("now_playing")
        if not self.track:
            return "Nothing is playing on Spotify right now."
        verb = "This is" if self.playing else "Paused on"
        if self.artist:
            return f"{verb} {self.track} by {self.artist}."
        return f"{verb} {self.track}."

    def set_volume(self, percent: int) -> str:
        self.calls.append(f"volume_set:{percent}")
        self._check_device()
        self.volume = max(0, min(100, int(percent)))
        return f"Volume set to {self.volume} percent."

    def change_volume(self, delta: int) -> str:
        self.calls.append(f"volume_change:{delta}")
        self._check_device()
        self.volume = max(0, min(100, self.volume + int(delta)))
        direction = "up" if delta >= 0 else "down"
        return f"Volume {direction} to {self.volume} percent."


class FakeSpotifyControl(SpotifyControllerImpl):
    """Alias for tests that want an explicit Fake* name."""

    def __init__(
        self,
        *,
        player: FakeSpotifyPlayer | None = None,
        configured: bool = True,
        signed_in: bool = True,
    ) -> None:
        super().__init__(
            player=player or FakeSpotifyPlayer(),
            configured=configured,
            signed_in=signed_in,
            works_offline=True,
        )


def sample_spotify(
    *,
    player: FakeSpotifyPlayer | None = None,
    configured: bool = True,
    signed_in: bool = True,
) -> SpotifyControllerImpl:
    """Ready-to-use controller with sample playback data (no OAuth, no network)."""
    return SpotifyControllerImpl(
        player=player or FakeSpotifyPlayer(),
        configured=configured,
        signed_in=signed_in,
        works_offline=True,
    )
