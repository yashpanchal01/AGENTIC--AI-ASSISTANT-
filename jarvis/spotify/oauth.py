"""One-time Spotify OAuth — Authorization Code + PKCE, no client secret.

Free Spotify developer app + the user's own account ($0). The one-time login
opens a browser, catches the redirect on a localhost loopback port, exchanges
the code for tokens, and persists them via the guarded TokenStore (never in
markdown memory notes). Refresh is silent afterwards.

Everything uses the standard library (urllib + http.server) — no new deps.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jarvis.spotify.base import SpotifyError
from jarvis.spotify.tokens import TokenStore, spotify_token_store

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
DEFAULT_REDIRECT_PORT = 8898

# Playback state + control + now-playing. Nothing else (no library writes).
SCOPES: tuple[str, ...] = (
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
)

# (method, url, headers, body) → (status, response_bytes). Tests inject fakes.
HttpFn = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


def urllib_http(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes]:
    """Default transport: stdlib urllib with a short timeout."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def default_client_id() -> str | None:
    env = (os.environ.get("JARVIS_SPOTIFY_CLIENT_ID") or "").strip()
    return env or None


def default_redirect_port() -> int:
    env = (os.environ.get("JARVIS_SPOTIFY_PORT") or "").strip()
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    return DEFAULT_REDIRECT_PORT


def redirect_uri(port: int) -> str:
    # Spotify requires an explicit loopback IP (http://127.0.0.1:PORT), and it
    # must exactly match the Redirect URI registered on the developer app.
    return f"http://127.0.0.1:{port}/callback"


def make_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(
    *, client_id: str, redirect: str, challenge: str, state: str
) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect,
        "scope": " ".join(SCOPES),
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
    }
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def _token_request(form: dict[str, str], http: HttpFn) -> dict[str, Any]:
    body = urllib.parse.urlencode(form).encode("ascii")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    status, raw = http("POST", TOKEN_URL, headers, body)
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        payload = {}
    if status >= 400 or "access_token" not in payload:
        detail = payload.get("error_description") or payload.get("error") or status
        raise SpotifyError(f"Spotify sign-in failed ({detail}).")
    return payload


def _normalize_payload(
    payload: dict[str, Any], *, client_id: str, previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Shape the stored token file; keep the old refresh token if not rotated."""
    refresh = payload.get("refresh_token") or (previous or {}).get("refresh_token")
    expires_in = int(payload.get("expires_in") or 3600)
    return {
        "provider": "spotify",
        "client_id": client_id,
        "access_token": payload.get("access_token"),
        "refresh_token": refresh,
        "expires_at": time.time() + expires_in,
        "scope": payload.get("scope") or " ".join(SCOPES),
        "token_type": payload.get("token_type") or "Bearer",
    }


def exchange_code(
    code: str,
    *,
    client_id: str,
    redirect: str,
    verifier: str,
    http: HttpFn | None = None,
) -> dict[str, Any]:
    """Swap the authorization code for tokens (PKCE — no client secret)."""
    payload = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": client_id,
            "code_verifier": verifier,
        },
        http or urllib_http,
    )
    return _normalize_payload(payload, client_id=client_id)


def refresh_access_token(
    data: dict[str, Any], *, client_id: str | None = None, http: HttpFn | None = None
) -> dict[str, Any]:
    """Refresh an expired access token; returns the new stored payload."""
    cid = client_id or data.get("client_id")
    refresh = data.get("refresh_token")
    if not cid or not refresh:
        raise SpotifyError(
            "You're not signed in to Spotify yet. "
            "Run jarvis --spotify-login once to link your account."
        )
    payload = _token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": cid,
        },
        http or urllib_http,
    )
    return _normalize_payload(payload, client_id=cid, previous=data)


def is_signed_in(token_store: TokenStore | None = None) -> bool:
    store = token_store or spotify_token_store()
    try:
        data = store.load()
    except Exception:  # noqa: BLE001 — a corrupt token file means "not signed in"
        return False
    if not data:
        return False
    return bool(data.get("refresh_token") or data.get("access_token"))


def run_spotify_login(
    *,
    client_id: str | None = None,
    token_store: TokenStore | None = None,
    port: int | None = None,
    open_browser: bool = True,
    timeout_s: float = 300.0,
    http: HttpFn | None = None,
) -> Path:
    """Interactive one-time PKCE login; writes tokens via TokenStore.

    Starts a tiny localhost server on the loopback port, opens the Spotify
    consent page, waits for the redirect, exchanges the code, saves tokens.
    Returns the path of the saved token file.
    """
    cid = client_id or default_client_id()
    if not cid:
        raise SpotifyError(
            "No Spotify client ID configured. Follow docs/spotify-setup.md: "
            "create a free app at developer.spotify.com, then set "
            "JARVIS_SPOTIFY_CLIENT_ID or \"spotify_client_id\" in settings.json."
        )
    listen_port = port or default_redirect_port()
    redirect = redirect_uri(listen_port)
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(16)
    url = build_authorize_url(
        client_id=cid, redirect=redirect, challenge=challenge, state=state
    )

    code = _wait_for_code(
        port=listen_port,
        expected_state=state,
        authorize_url=url,
        open_browser=open_browser,
        timeout_s=timeout_s,
    )

    data = exchange_code(
        code, client_id=cid, redirect=redirect, verifier=verifier, http=http
    )
    store = token_store or spotify_token_store()
    store.save(data)
    return store.path


def _wait_for_code(
    *,
    port: int,
    expected_state: str,
    authorize_url: str,
    open_browser: bool,
    timeout_s: float,
) -> str:
    """Serve the loopback redirect once and return the authorization code."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    box: dict[str, str] = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — http.server API
            parsed = urllib.parse.urlparse(self.path)
            params = dict(urllib.parse.parse_qsl(parsed.query))
            ok = (
                parsed.path == "/callback"
                and params.get("state") == expected_state
                and "code" in params
            )
            if ok:
                box["code"] = params["code"]
                page = (
                    "<html><body><h2>JARVIS is linked to Spotify.</h2>"
                    "<p>You can close this tab and go back to the terminal.</p>"
                    "</body></html>"
                )
                self.send_response(200)
            else:
                box.setdefault(
                    "error", params.get("error") or "unexpected redirect"
                )
                page = (
                    "<html><body><h2>Spotify sign-in failed.</h2>"
                    "<p>Close this tab and try again from the terminal.</p>"
                    "</body></html>"
                )
                self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

        def log_message(self, *args: Any) -> None:  # silence request lines
            return

    try:
        server = HTTPServer(("127.0.0.1", port), _Handler)
    except OSError as exc:
        raise SpotifyError(
            f"Couldn't open the login port {port} ({exc}). "
            "Close whatever is using it, or set JARVIS_SPOTIFY_PORT to a free "
            "port and update the app's Redirect URI to match."
        ) from exc

    with server:
        server.timeout = 1.0
        print("Opening Spotify sign-in in your browser…")
        print(f"If nothing opens, paste this into a browser:\n  {authorize_url}")
        if open_browser:
            import webbrowser

            try:
                webbrowser.open(authorize_url)
            except Exception:  # noqa: BLE001 — URL is already printed
                pass
        deadline = time.monotonic() + timeout_s
        while "code" not in box and "error" not in box:
            if time.monotonic() > deadline:
                raise SpotifyError(
                    "Spotify sign-in timed out — no browser redirect arrived."
                )
            server.handle_request()

    if "code" not in box:
        raise SpotifyError(f"Spotify sign-in failed ({box.get('error')}).")
    return box["code"]
