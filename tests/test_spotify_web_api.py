"""LiveSpotify + PKCE OAuth against a fake HTTP transport — no network.

Asserts external behavior: which endpoints are hit, what is spoken back,
and that tokens refresh/persist correctly. Never inspects internals.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path

import pytest

from jarvis.spotify.base import SpotifyError
from jarvis.spotify.oauth import (
    build_authorize_url,
    exchange_code,
    make_pkce_pair,
    refresh_access_token,
)
from jarvis.spotify.tokens import TokenStore
from jarvis.spotify.web_api import LiveSpotify


class FakeHttp:
    """Routes (method, path) → (status, json payload); records every call."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], tuple[int, object]] = {}
        self.calls: list[dict] = []

    def add(self, method: str, path: str, status: int, payload: object = None) -> None:
        self.routes[(method, path)] = (status, payload)

    def __call__(self, method, url, headers, body):
        parsed = urllib.parse.urlparse(url)
        self.calls.append(
            {
                "method": method,
                "path": parsed.path,
                "query": dict(urllib.parse.parse_qsl(parsed.query)),
                "headers": dict(headers),
                "body": json.loads(body) if body and body[:1] == b"{" else body,
            }
        )
        status, payload = self.routes.get((method, parsed.path), (200, None))
        raw = b"" if payload is None else json.dumps(payload).encode("utf-8")
        return status, raw


def _store(tmp_path: Path, **overrides) -> TokenStore:
    store = TokenStore(
        path=tmp_path / "secure" / "spotify_token.json",
        memory_notes_root=tmp_path / "memory",
    )
    payload = {
        "provider": "spotify",
        "client_id": "cid-123",
        "access_token": "AT-1",
        "refresh_token": "RT-1",
        "expires_at": time.time() + 3600,
    }
    payload.update(overrides)
    store.save(payload)
    return store


def _player(tmp_path: Path, http: FakeHttp, **token_overrides) -> LiveSpotify:
    return LiveSpotify(
        client_id="cid-123",
        token_store=_store(tmp_path, **token_overrides),
        http=http,
    )


# --- playback endpoints -------------------------------------------------------


def test_play_named_track_searches_then_plays(tmp_path: Path) -> None:
    http = FakeHttp()
    http.add(
        "GET",
        "/v1/search",
        200,
        {
            "tracks": {
                "items": [
                    {
                        "name": "Bohemian Rhapsody",
                        "uri": "spotify:track:abc",
                        "artists": [{"name": "Queen"}],
                    }
                ]
            }
        },
    )
    http.add("PUT", "/v1/me/player/play", 204)

    reply = _player(tmp_path, http).play("bohemian rhapsody by queen", "track")

    assert reply == "Playing Bohemian Rhapsody by Queen."
    play_call = next(c for c in http.calls if c["path"] == "/v1/me/player/play")
    assert play_call["body"] == {"uris": ["spotify:track:abc"]}
    search_call = next(c for c in http.calls if c["path"] == "/v1/search")
    assert search_call["query"]["q"] == "bohemian rhapsody by queen"
    assert search_call["headers"]["Authorization"] == "Bearer AT-1"


def test_play_playlist_uses_context_uri(tmp_path: Path) -> None:
    http = FakeHttp()
    http.add(
        "GET",
        "/v1/search",
        200,
        {
            "playlists": {
                "items": [{"name": "Chill Vibes", "uri": "spotify:playlist:xyz"}]
            }
        },
    )
    http.add("PUT", "/v1/me/player/play", 204)

    reply = _player(tmp_path, http).play("chill vibes", "playlist")

    assert reply == "Playing the playlist Chill Vibes."
    play_call = next(c for c in http.calls if c["path"] == "/v1/me/player/play")
    assert play_call["body"] == {"context_uri": "spotify:playlist:xyz"}


def test_play_nothing_found_spoken_plainly(tmp_path: Path) -> None:
    http = FakeHttp()
    http.add("GET", "/v1/search", 200, {"tracks": {"items": []}})

    reply = _player(tmp_path, http).play("zanzibar dreams", "track")

    assert "couldn't find" in reply.lower()


def test_pause_resume_next_hit_player_endpoints(tmp_path: Path) -> None:
    http = FakeHttp()
    http.add("PUT", "/v1/me/player/pause", 204)
    http.add("PUT", "/v1/me/player/play", 204)
    http.add("POST", "/v1/me/player/next", 204)
    player = _player(tmp_path, http)

    assert player.pause() == "Paused."
    assert player.resume() == "Resuming."
    assert player.next_track() == "Skipped."
    paths = [(c["method"], c["path"]) for c in http.calls]
    assert ("PUT", "/v1/me/player/pause") in paths
    assert ("PUT", "/v1/me/player/play") in paths
    assert ("POST", "/v1/me/player/next") in paths


def test_now_playing_reads_current_track(tmp_path: Path) -> None:
    http = FakeHttp()
    http.add(
        "GET",
        "/v1/me/player/currently-playing",
        200,
        {
            "is_playing": True,
            "item": {"name": "Midnight City", "artists": [{"name": "M83"}]},
        },
    )

    reply = _player(tmp_path, http).now_playing()

    assert reply == "This is Midnight City by M83."


def test_now_playing_nothing(tmp_path: Path) -> None:
    http = FakeHttp()
    http.add("GET", "/v1/me/player/currently-playing", 204)

    reply = _player(tmp_path, http).now_playing()

    assert "nothing is playing" in reply.lower()


def test_set_volume_sends_percent(tmp_path: Path) -> None:
    http = FakeHttp()
    http.add("PUT", "/v1/me/player/volume", 204)

    reply = _player(tmp_path, http).set_volume(35)

    assert "35" in reply
    call = next(c for c in http.calls if c["path"] == "/v1/me/player/volume")
    assert call["query"] == {"volume_percent": "35"}


def test_change_volume_reads_then_adjusts(tmp_path: Path) -> None:
    http = FakeHttp()
    http.add("GET", "/v1/me/player", 200, {"device": {"volume_percent": 50}})
    http.add("PUT", "/v1/me/player/volume", 204)

    reply = _player(tmp_path, http).change_volume(10)

    assert "60" in reply
    call = next(c for c in http.calls if c["path"] == "/v1/me/player/volume")
    assert call["query"] == {"volume_percent": "60"}


# --- plain-language failures ----------------------------------------------------


def test_no_active_device_404_is_plain(tmp_path: Path) -> None:
    http = FakeHttp()
    http.add("PUT", "/v1/me/player/pause", 404, {"error": {"message": "Device not found"}})

    with pytest.raises(SpotifyError) as err:
        _player(tmp_path, http).pause()

    text = str(err.value).lower()
    assert "device" in text
    assert "404" not in text  # plain language, not HTTP jargon


def test_premium_required_403_is_plain(tmp_path: Path) -> None:
    http = FakeHttp()
    http.add("PUT", "/v1/me/player/next", 403, {"error": {"reason": "PREMIUM_REQUIRED"}})
    http.add("POST", "/v1/me/player/next", 403, {"error": {"reason": "PREMIUM_REQUIRED"}})

    with pytest.raises(SpotifyError) as err:
        _player(tmp_path, http).next_track()

    assert "premium" in str(err.value).lower()


def test_expired_sign_in_401_is_plain(tmp_path: Path) -> None:
    http = FakeHttp()
    http.add("PUT", "/v1/me/player/pause", 401)

    with pytest.raises(SpotifyError) as err:
        _player(tmp_path, http).pause()

    assert "--spotify-login" in str(err.value)


# --- token refresh ---------------------------------------------------------------


def test_expired_access_token_refreshes_and_persists(tmp_path: Path) -> None:
    http = FakeHttp()
    http.add(
        "POST",
        "/api/token",
        200,
        {"access_token": "AT-2", "expires_in": 3600},
    )
    http.add("PUT", "/v1/me/player/pause", 204)
    store = _store(tmp_path, expires_at=time.time() - 10)
    player = LiveSpotify(client_id="cid-123", token_store=store, http=http)

    assert player.pause() == "Paused."

    pause_call = next(c for c in http.calls if c["path"] == "/v1/me/player/pause")
    assert pause_call["headers"]["Authorization"] == "Bearer AT-2"
    saved = store.load()
    assert saved["access_token"] == "AT-2"
    # Refresh token survives when Spotify does not rotate it.
    assert saved["refresh_token"] == "RT-1"


# --- PKCE oauth helpers ------------------------------------------------------------


def test_pkce_pair_is_s256_of_verifier() -> None:
    import base64
    import hashlib

    verifier, challenge = make_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected
    assert 43 <= len(verifier) <= 128


def test_authorize_url_has_pkce_and_no_secret() -> None:
    url = build_authorize_url(
        client_id="cid-123",
        redirect="http://127.0.0.1:8898/callback",
        challenge="chal",
        state="st",
    )
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert q["client_id"] == "cid-123"
    assert q["code_challenge_method"] == "S256"
    assert q["code_challenge"] == "chal"
    assert q["response_type"] == "code"
    assert "client_secret" not in q
    assert "user-modify-playback-state" in q["scope"]


def test_exchange_code_normalizes_token_payload() -> None:
    http = FakeHttp()
    http.add(
        "POST",
        "/api/token",
        200,
        {"access_token": "AT-1", "refresh_token": "RT-1", "expires_in": 3600},
    )

    data = exchange_code(
        "auth-code",
        client_id="cid-123",
        redirect="http://127.0.0.1:8898/callback",
        verifier="ver",
        http=http,
    )

    assert data["access_token"] == "AT-1"
    assert data["refresh_token"] == "RT-1"
    assert data["client_id"] == "cid-123"
    assert data["expires_at"] > time.time()
    body = urllib.parse.parse_qs(http.calls[0]["body"].decode())
    assert body["grant_type"] == ["authorization_code"]
    assert body["code_verifier"] == ["ver"]
    assert "client_secret" not in body  # PKCE — public client, no secret


def test_refresh_without_refresh_token_says_sign_in() -> None:
    with pytest.raises(SpotifyError) as err:
        refresh_access_token({"access_token": "AT"}, client_id="cid-123")
    assert "--spotify-login" in str(err.value)


def test_token_store_rejects_memory_notes_tree(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    with pytest.raises(ValueError):
        TokenStore(path=memory / "spotify_token.json", memory_notes_root=memory)
