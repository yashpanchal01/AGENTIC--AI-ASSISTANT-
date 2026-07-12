"""Live Spotify Web API player — stdlib HTTP, plain-language failures.

All methods return the sentence JARVIS should speak. Known failures raise
:class:`SpotifyError` whose message is already speakable (no active device,
Premium required, expired sign-in). Tests inject a fake ``http`` transport.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from typing import Any

from jarvis.spotify.base import SpotifyError
from jarvis.spotify.oauth import HttpFn, refresh_access_token, urllib_http
from jarvis.spotify.tokens import TokenStore, spotify_token_store

API_BASE = "https://api.spotify.com/v1"

NO_ACTIVE_DEVICE = (
    "Spotify isn't active on any device — open the Spotify app, "
    "press play once, and try again."
)
PREMIUM_REQUIRED = (
    "Spotify says controlling playback needs a Premium account, "
    "so I can't do that on this account."
)
SIGN_IN_EXPIRED = (
    "My Spotify sign-in has expired. Run jarvis --spotify-login once to fix it."
)
NOTHING_PLAYING = "Nothing is playing on Spotify right now."

# Refresh slightly early so a token never expires mid-request.
_EXPIRY_MARGIN_S = 30.0


class LiveSpotify:
    """Playback control + search over the Spotify Web API (PKCE tokens)."""

    def __init__(
        self,
        *,
        client_id: str | None = None,
        token_store: TokenStore | None = None,
        http: HttpFn | None = None,
    ) -> None:
        self._client_id = client_id
        self._store = token_store or spotify_token_store()
        self._http = http or urllib_http

    # -- voice-facing operations ------------------------------------------

    def play(self, query: str, kind: str = "any") -> str:
        q = (query or "").strip()
        if not q:
            return self.resume()
        found = self._search(q, kind)
        if found is None:
            return f"I couldn't find {q} on Spotify."
        what, name, artist, uri = found
        if what == "track":
            self._call("PUT", "/me/player/play", body={"uris": [uri]})
            return f"Playing {name} by {artist}." if artist else f"Playing {name}."
        if what == "playlist":
            self._call("PUT", "/me/player/play", body={"context_uri": uri})
            return f"Playing the playlist {name}."
        self._call("PUT", "/me/player/play", body={"context_uri": uri})
        return f"Playing music by {name}."

    def pause(self) -> str:
        self._call("PUT", "/me/player/pause")
        return "Paused."

    def resume(self) -> str:
        self._call("PUT", "/me/player/play")
        return "Resuming."

    def next_track(self) -> str:
        self._call("POST", "/me/player/next")
        return "Skipped."

    def now_playing(self) -> str:
        status, payload = self._call("GET", "/me/player/currently-playing")
        item = (payload or {}).get("item") or {}
        if status == 204 or not item:
            return NOTHING_PLAYING
        name = item.get("name") or "an unknown track"
        artists = ", ".join(
            a.get("name", "") for a in item.get("artists") or [] if a.get("name")
        )
        playing = (payload or {}).get("is_playing", True)
        verb = "This is" if playing else "Paused on"
        return f"{verb} {name} by {artists}." if artists else f"{verb} {name}."

    def set_volume(self, percent: int) -> str:
        level = max(0, min(100, int(percent)))
        self._call("PUT", "/me/player/volume", query={"volume_percent": level})
        return f"Volume set to {level} percent."

    def change_volume(self, delta: int) -> str:
        status, payload = self._call("GET", "/me/player")
        device = (payload or {}).get("device") or {}
        current = device.get("volume_percent")
        if status == 204 or current is None:
            raise SpotifyError(NO_ACTIVE_DEVICE)
        level = max(0, min(100, int(current) + int(delta)))
        self._call("PUT", "/me/player/volume", query={"volume_percent": level})
        direction = "up" if delta >= 0 else "down"
        return f"Volume {direction} to {level} percent."

    # -- plumbing -----------------------------------------------------------

    def _search(self, query: str, kind: str) -> tuple[str, str, str, str] | None:
        """Return (what, name, artist, uri) for the best match, or None."""
        types = {
            "track": "track",
            "artist": "artist",
            "playlist": "playlist",
        }.get(kind, "track,playlist")
        _, payload = self._call(
            "GET",
            "/search",
            query={"q": query, "type": types, "limit": 3},
        )
        payload = payload or {}

        def _first(section: str) -> dict[str, Any] | None:
            items = (payload.get(section) or {}).get("items") or []
            for item in items:
                if item:  # Spotify may pad with nulls
                    return item
            return None

        track = _first("tracks")
        if kind in ("track", "any") and track:
            artists = ", ".join(
                a.get("name", "")
                for a in track.get("artists") or []
                if a.get("name")
            )
            return ("track", track.get("name") or query, artists, track["uri"])
        playlist = _first("playlists")
        if kind in ("playlist", "any") and playlist:
            return ("playlist", playlist.get("name") or query, "", playlist["uri"])
        artist = _first("artists")
        if kind == "artist" and artist:
            return ("artist", artist.get("name") or query, "", artist["uri"])
        return None

    def _access_token(self) -> str:
        data = self._store.load()
        if not data or not (data.get("access_token") or data.get("refresh_token")):
            raise SpotifyError(
                "You're not signed in to Spotify yet. "
                "Run jarvis --spotify-login once to link your account."
            )
        expires_at = float(data.get("expires_at") or 0)
        if expires_at <= time.time() + _EXPIRY_MARGIN_S:
            try:
                data = refresh_access_token(
                    data, client_id=self._client_id, http=self._http
                )
            except SpotifyError:
                raise
            except Exception as exc:  # noqa: BLE001 — plain message, no stack trace
                raise SpotifyError(SIGN_IN_EXPIRED) from exc
            self._store.save(data)
        token = data.get("access_token")
        if not token:
            raise SpotifyError(SIGN_IN_EXPIRED)
        return str(token)

    def _call(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        url = API_BASE + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        raw_body: bytes | None = None
        if body is not None:
            raw_body = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        status, raw = self._http(method, url, headers, raw_body)
        payload: dict[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
                if isinstance(parsed, dict):
                    payload = parsed
            except ValueError:
                payload = {}

        if status == 401:
            raise SpotifyError(SIGN_IN_EXPIRED)
        if status == 403:
            raise SpotifyError(PREMIUM_REQUIRED)
        if status == 404:
            raise SpotifyError(NO_ACTIVE_DEVICE)
        if status == 429:
            raise SpotifyError("Spotify asked me to slow down — try again in a moment.")
        if status >= 400:
            message = ((payload.get("error") or {}).get("message") or "").strip()
            raise SpotifyError(
                f"Spotify said no: {message}." if message
                else "Spotify returned an error, so I couldn't do that."
            )
        return status, payload
