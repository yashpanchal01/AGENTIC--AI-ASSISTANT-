"""SpotifyController: route music voice intents to a player (issue 09)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from jarvis.spotify.base import SpotifyError, SpotifyResult
from jarvis.spotify.intents import SpotifyIntentKind, classify
from jarvis.types import Action


@runtime_checkable
class SpotifyPlayer(Protocol):
    """Playback seam — Live Web API in production, scriptable fake in tests.

    Each method returns the sentence JARVIS speaks; known failures raise
    SpotifyError with a plain, speakable message.
    """

    def play(self, query: str, kind: str = "any") -> str: ...
    def pause(self) -> str: ...
    def resume(self) -> str: ...
    def next_track(self) -> str: ...
    def now_playing(self) -> str: ...
    def set_volume(self, percent: int) -> str: ...
    def change_volume(self, delta: int) -> str: ...


VOLUME_STEP = 10

NOT_CONFIGURED_REPLY = (
    "Spotify isn't set up yet. Follow the one-time guide in "
    "docs/spotify-setup.md to link your account."
)
NOT_SIGNED_IN_REPLY = (
    "You're not signed in to Spotify yet. "
    "Run jarvis --spotify-login once to link your account."
)
GENERIC_FAILURE_REPLY = "I couldn't reach Spotify right now."


@dataclass
class SpotifyControllerImpl:
    """Concrete hub: intent classify → player calls with plain spoken errors."""

    player: SpotifyPlayer | None = None
    # No client ID at all → point at the setup doc instead of erroring.
    configured: bool = True
    # Client ID present but the one-time login has not happened yet.
    signed_in: bool = True
    # Fakes answer without the network; the live Web API cannot.
    works_offline: bool = False

    def try_handle(self, utterance: str) -> SpotifyResult | None:
        intent = classify(utterance)
        if intent.kind is SpotifyIntentKind.UNRELATED:
            return None

        if not self.configured:
            return SpotifyResult(
                reply=NOT_CONFIGURED_REPLY,
                actions=(),
                ok=False,
                error="not_configured",
            )
        if not self.signed_in:
            return SpotifyResult(
                reply=NOT_SIGNED_IN_REPLY,
                actions=(),
                ok=False,
                error="not_signed_in",
            )

        try:
            return self._dispatch(intent.kind, intent.query, intent.hint, intent.level)
        except SpotifyError as exc:
            # Message is already plain and speakable (no device, Premium, …).
            return SpotifyResult(
                reply=str(exc),
                actions=(),
                ok=False,
                error="spotify_error",
            )
        except Exception as exc:  # noqa: BLE001 — speak plain, never crash
            return SpotifyResult(
                reply=GENERIC_FAILURE_REPLY,
                actions=(),
                ok=False,
                error=type(exc).__name__,
            )

    def _dispatch(
        self,
        kind: SpotifyIntentKind,
        query: str,
        hint: str,
        level: int | None,
    ) -> SpotifyResult:
        player = self.player
        if player is None:
            raise RuntimeError("spotify_unavailable")

        if kind is SpotifyIntentKind.PLAY_NAMED:
            return SpotifyResult(
                reply=player.play(query, hint),
                actions=(Action(name="spotify_play", detail=query),),
            )
        if kind is SpotifyIntentKind.PAUSE:
            return SpotifyResult(
                reply=player.pause(),
                actions=(Action(name="spotify_pause", detail=""),),
            )
        if kind is SpotifyIntentKind.RESUME:
            return SpotifyResult(
                reply=player.resume(),
                actions=(Action(name="spotify_resume", detail=""),),
            )
        if kind is SpotifyIntentKind.NEXT:
            return SpotifyResult(
                reply=player.next_track(),
                actions=(Action(name="spotify_next", detail=""),),
            )
        if kind is SpotifyIntentKind.NOW_PLAYING:
            return SpotifyResult(
                reply=player.now_playing(),
                actions=(Action(name="spotify_now_playing", detail=""),),
            )
        if kind is SpotifyIntentKind.VOLUME_SET:
            return SpotifyResult(
                reply=player.set_volume(int(level or 0)),
                actions=(Action(name="spotify_volume", detail=str(level)),),
            )
        if kind is SpotifyIntentKind.VOLUME_UP:
            return SpotifyResult(
                reply=player.change_volume(VOLUME_STEP),
                actions=(Action(name="spotify_volume", detail="up"),),
            )
        if kind is SpotifyIntentKind.VOLUME_DOWN:
            return SpotifyResult(
                reply=player.change_volume(-VOLUME_STEP),
                actions=(Action(name="spotify_volume", detail="down"),),
            )
        return SpotifyResult(reply="I'm not sure how to help with that music request.")


def build_spotify(config=None, *, force_fake: bool = False) -> SpotifyControllerImpl:
    """Build the controller from config/env, or unsigned / fake for demos.

    Never raises — an unconfigured or broken setup degrades to a controller
    that answers music intents with a short spoken setup pointer.
    """
    if force_fake:
        from jarvis.spotify.fake import sample_spotify

        return sample_spotify()

    from jarvis.spotify.oauth import default_client_id

    client_id = (getattr(config, "spotify_client_id", None) or "").strip() or None
    if client_id is None:
        client_id = default_client_id()
    if not client_id:
        return SpotifyControllerImpl(configured=False)

    try:
        from jarvis.spotify.oauth import is_signed_in
        from jarvis.spotify.tokens import spotify_token_store
        from jarvis.spotify.web_api import LiveSpotify

        token_path = getattr(config, "spotify_token_path", None)
        store = spotify_token_store(token_path)
        if not is_signed_in(store):
            return SpotifyControllerImpl(configured=True, signed_in=False)
        return SpotifyControllerImpl(
            player=LiveSpotify(client_id=client_id, token_store=store),
            configured=True,
            signed_in=True,
        )
    except Exception:  # noqa: BLE001 — degrade rather than crash the CLI
        return SpotifyControllerImpl(configured=True, signed_in=False)
