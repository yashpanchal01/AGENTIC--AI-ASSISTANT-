"""One-time Google OAuth covering Gmail + Calendar read-only scopes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from jarvis.google.tokens import TokenStore, default_token_path

# Single consent screen; both products share the token file.
SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
)


def default_client_secrets_path() -> Path:
    env = os.environ.get("JARVIS_GOOGLE_CLIENT_SECRETS")
    if env:
        return Path(env).expanduser()
    # Conventional locations (never under memory notes).
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            p = Path(base) / "Jarvis" / "google_client_secrets.json"
            if p.is_file():
                return p
    home = Path.home() / ".config" / "jarvis" / "google_client_secrets.json"
    return home


def run_oauth_login(
    *,
    client_secrets: Path | None = None,
    token_store: TokenStore | None = None,
    open_browser: bool = True,
) -> Path:
    """Interactive installed-app OAuth; writes tokens via TokenStore.

    Requires optional deps: google-auth-oauthlib, google-auth.
    Returns the path of the saved token file.
    """
    secrets = client_secrets or default_client_secrets_path()
    if not secrets.is_file():
        raise FileNotFoundError(
            f"Google OAuth client secrets not found at {secrets}. "
            "Download a Desktop OAuth client JSON from Google Cloud Console "
            "and set JARVIS_GOOGLE_CLIENT_SECRETS, or place it at that path. "
            f"Requested scopes: {', '.join(SCOPES)}"
        )

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError(
            "Google OAuth requires optional deps. Install with: "
            'py -3.13 -m pip install -e ".[google]"'
        ) from exc

    store = token_store or TokenStore(path=default_token_path())
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), list(SCOPES))
    if open_browser:
        creds = flow.run_local_server(port=0)
    else:
        creds = flow.run_console()

    payload = _credentials_to_payload(creds)
    # Ensure both products are recorded on the token for audits / debugging.
    payload["scopes"] = list(SCOPES)
    payload["products"] = ["gmail", "calendar"]
    store.save(payload)
    return store.path


def load_credentials(token_store: TokenStore | None = None) -> Any | None:
    """Load stored credentials, refreshing if needed. Returns None if missing."""
    store = token_store or TokenStore(path=default_token_path())
    data = store.load()
    if not data:
        return None
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise RuntimeError(
            'Google API requires optional deps: py -3.13 -m pip install -e ".[google]"'
        ) from exc

    creds = Credentials.from_authorized_user_info(data, list(SCOPES))
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        store.save(_credentials_to_payload(creds))
    return creds


def is_signed_in(token_store: TokenStore | None = None) -> bool:
    store = token_store or TokenStore(path=default_token_path())
    data = store.load()
    if not data:
        return False
    return bool(data.get("refresh_token") or data.get("token"))


def _credentials_to_payload(creds: Any) -> dict[str, Any]:
    """Serialize google.oauth2.credentials.Credentials without leaking via notes."""
    # Prefer the library's own JSON shape when available.
    if hasattr(creds, "to_json"):
        return json.loads(creds.to_json())
    return {
        "token": getattr(creds, "token", None),
        "refresh_token": getattr(creds, "refresh_token", None),
        "token_uri": getattr(creds, "token_uri", None),
        "client_id": getattr(creds, "client_id", None),
        "client_secret": getattr(creds, "client_secret", None),
        "scopes": list(getattr(creds, "scopes", []) or SCOPES),
    }
