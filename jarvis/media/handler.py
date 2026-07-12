"""Find a local media file and open it with the OS (real launch, no brain)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from jarvis.media.base import MediaResult
from jarvis.media.intents import MediaIntentKind, classify
from jarvis.types import Action

MEDIA_EXTS: frozenset[str] = frozenset(
    {
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".wmv",
        ".webm",
        ".m4v",
        ".mp3",
        ".flac",
        ".wav",
        ".m4a",
        ".aac",
    }
)

_PENDING = re.compile(r"^\.pending-\d+-", re.I)
_FUZZY_TOKEN = 0.72

OpenFn = Callable[[Path], None]
# post_layout(side|fullscreen) — injected in tests
LayoutFn = Callable[..., Any]


def default_open(path: Path) -> None:
    """Launch *path* with the OS default app. Raises on hard failure."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], close_fds=True)
        return
    subprocess.Popen(["xdg-open", str(path)], close_fds=True)


def open_media(path: Path, *, fullscreen: bool = False) -> str:
    """Open *path*. Prefer VLC with ``--fullscreen`` for true video fullscreen.

    Returns how it was opened: ``vlc-fullscreen`` | ``vlc`` | ``default``.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if sys.platform == "win32":
        try:
            from jarvis.windows.win32api import open_in_vlc

            # Always prefer VLC when installed so layout/fullscreen is reliable.
            proc = open_in_vlc(path, fullscreen=fullscreen)
            if proc is not None:
                return "vlc-fullscreen" if fullscreen else "vlc"
        except Exception:
            pass
    if fullscreen:
        # No VLC: open default then caller may try F11 / maximize fallback.
        default_open(path)
        return "default"
    default_open(path)
    return "default"


def default_fullscreen_player() -> object:
    from jarvis.windows.win32api import fullscreen_media_player

    return fullscreen_media_player()


def default_snap_player(side: str) -> object:
    from jarvis.windows.win32api import snap_media_player

    return snap_media_player(side)


def _tokens(s: str) -> list[str]:
    s = s.lower()
    s = _PENDING.sub("", s)
    s = re.sub(r"[\W_]+", " ", s)
    stop = {
        "the", "a", "an", "and", "or", "of", "to", "in", "my", "for",
        "on", "with", "from", "folder", "please", "keep", "it", "half",
        "screen", "side",
    }
    return [t for t in s.split() if len(t) > 1 and t not in stop]


def _token_hit(q: str, name_toks: set[str]) -> float:
    """Exact / prefix hit, or careful fuzzy (same first letter, not short chaos)."""
    if q in name_toks:
        return 1.0
    # Substring only for longer tokens (avoid "at" in "hail", etc.)
    if len(q) >= 4 and any(q in n or n in q for n in name_toks if min(len(q), len(n)) >= 4):
        return 0.95
    # Short tokens: exact only — "brave" must not ≈ "grave"
    if len(q) < 5:
        return 0.0
    best = 0.0
    for n in name_toks:
        if len(n) < 4:
            continue
        if q[0] != n[0]:
            continue  # first letter must match (blocks brave→grave)
        if abs(len(q) - len(n)) > max(2, len(q) // 2):
            continue
        r = SequenceMatcher(None, q, n).ratio()
        if r > best:
            best = r
    # Stricter than bare 0.72 so one-letter edits on short words still need care
    need = max(_FUZZY_TOKEN, 0.82 if len(q) <= 6 else _FUZZY_TOKEN)
    return best if best >= need else 0.0


def score_match(query: str, path: Path) -> float:
    q = _tokens(query)
    if not q:
        return 0.0
    stem = path.stem
    stem = re.sub(r"\(\d{4}\)$", "", stem).strip()
    name_toks = set(_tokens(stem))
    if not name_toks:
        return 0.0
    hits = [_token_hit(t, name_toks) for t in q]
    # Require every query token to contribute something — no "brave"→random file
    if any(h <= 0.0 for h in hits):
        return 0.0
    return sum(hits) / len(q)


def find_media(
    query: str,
    roots: Iterable[Path],
    *,
    min_score: float = 0.55,
) -> Path | None:
    q = (query or "").strip()
    if not q:
        return None
    best: Path | None = None
    best_score = 0.0
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for p in entries:
            if not p.is_file():
                continue
            if p.suffix.lower() not in MEDIA_EXTS:
                continue
            sc = score_match(q, p)
            if sc < min_score:
                continue
            pending = bool(_PENDING.match(p.name))
            if best is None or sc > best_score + 1e-9:
                best, best_score = p, sc
            elif abs(sc - best_score) < 1e-9 and best is not None:
                if _PENDING.match(best.name) and not pending:
                    best = p
    return best


@dataclass
class LocalMediaHandler:
    """classify → search → open (prefer VLC) → optional true-FS / half-snap."""

    roots: tuple[Path, ...] = field(default_factory=tuple)
    open_fn: OpenFn | None = None  # if set, used instead of open_media
    fullscreen_fn: LayoutFn = field(default=default_fullscreen_player)
    snap_fn: LayoutFn = field(default=default_snap_player)
    min_score: float = 0.55
    layout_delay_s: float = 1.4

    def try_handle(self, utterance: str) -> MediaResult | None:
        intent = classify(utterance)
        if intent.kind is MediaIntentKind.UNRELATED:
            return None

        path = find_media(intent.query, self.roots, min_score=self.min_score)
        if path is None:
            if intent.kind is MediaIntentKind.PLAY_IF_MATCH:
                return None
            return MediaResult(
                reply=f'I couldn\'t find a media file matching "{intent.query}" '
                f"in your media folders.",
                actions=(),
                ok=False,
                error="not_found",
            )

        try:
            if self.open_fn is not None:
                self.open_fn(path)
                how = "custom"
            else:
                how = open_media(path, fullscreen=intent.fullscreen)
        except Exception as exc:  # noqa: BLE001
            return MediaResult(
                reply=f"I found {path.name} but couldn't open it.",
                actions=(),
                ok=False,
                error=type(exc).__name__,
            )

        actions: list[Action] = [
            Action(name="local_media_open", detail=f"{path}|{how}"),
        ]
        bits = [f"Playing {path.name}"]

        # True VLC fullscreen already applied via --fullscreen when how includes it.
        need_post_fs = intent.fullscreen and how not in ("vlc-fullscreen",)
        need_snap = intent.snap in ("left", "right")

        if intent.fullscreen and how == "vlc-fullscreen":
            actions.append(Action(name="local_media_fullscreen", detail="vlc-flag"))
            bits.append("in fullscreen")

        if need_post_fs or need_snap:
            delay = self.layout_delay_s
            fs_fn = self.fullscreen_fn
            snap_fn = self.snap_fn
            snap_side = intent.snap
            do_fs = need_post_fs
            do_snap = need_snap

            def _layout() -> None:
                import time

                time.sleep(delay)
                if do_fs:
                    try:
                        fs_fn()
                    except Exception:
                        pass
                if do_snap and snap_side:
                    try:
                        # Exit fullscreen first if we just entered it — snap needs a frame.
                        # If user asked both, snap wins for "half screen" intent.
                        snap_fn(snap_side)
                    except Exception:
                        pass

            threading.Thread(target=_layout, name="jarvis-media-layout", daemon=True).start()
            if do_fs:
                actions.append(Action(name="local_media_fullscreen", detail="post-key"))
                if "fullscreen" not in " ".join(bits):
                    bits.append("in fullscreen")
            if do_snap:
                actions.append(Action(name="local_media_snap", detail=str(snap_side)))
                bits.append(f"on the {snap_side} half of the screen")

        reply = " ".join(bits) + "."
        return MediaResult(reply=reply, actions=tuple(actions), ok=True)


def build_local_media(
    config=None,
    *,
    roots: tuple[Path, ...] | None = None,
    open_fn: OpenFn | None = None,
    fullscreen_fn: LayoutFn | None = None,
    snap_fn: LayoutFn | None = None,
) -> LocalMediaHandler:
    if roots is None:
        if config is not None and getattr(config, "approved_folders", None):
            base = tuple(Path(p) for p in config.approved_folders)
        else:
            home = Path.home()
            base = tuple(
                p
                for p in (
                    home / "Downloads",
                    home / "Documents",
                    home / "Desktop",
                    home / "Videos",
                )
                if p.is_dir()
            )
        videos = Path.home() / "Videos"
        if videos.is_dir() and videos not in base:
            base = base + (videos,)
        roots = base
    return LocalMediaHandler(
        roots=roots,
        open_fn=open_fn,
        fullscreen_fn=fullscreen_fn or default_fullscreen_player,
        snap_fn=snap_fn or default_snap_player,
    )
