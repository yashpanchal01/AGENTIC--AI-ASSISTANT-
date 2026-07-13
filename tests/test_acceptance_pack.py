"""Acceptance pack (issue 17): the user's five canonical tasks, end-to-end.

Each task runs through the REAL reflex → brain pipeline (:func:`jarvis.core.
handle_command`) with hermetic fakes injected for every OS/cloud surface, and
asserts three things:

1. the correct TIER handled it (via the audit ``path`` — a test fails if the
   wrong tier answers),
2. the correct action(s) fired, in order,
3. a per-tier latency budget (reflex < 1s; the brain path completes inline via
   the fakes and is never a silent stall).

Tiers on ``main`` (the issue-14 router is shelved — see the correction in the
issue): reflex local handlers (apps / system / media / windows / spotify) →
brain + in-process MCP tool bridge. There is no middle router tier.

    (a) "open the screen recording we just captured" → system reflex
        (latest-file). A paraphrase the reflex regex misses → brain + bridge.
    (b) "open spotify and play the next music"        → brain + bridge (2 steps)
    (c) "close all the windows"  (means MINIMIZE all)  → windows reflex
    (d) "dim my brightness to zero"                    → system reflex
    (e) "open brave and vs code side by side …"        → brain + bridge

No real Claude and no real OS: FakeBrain (scripted to drive the bridge tools
like Claude would) plus injected fake ops. Real-OS variants for (a)/(c)/(d)
live in ``test_acceptance_pack_os_smoke.py`` behind the ``os_smoke`` marker.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.apps.handler import AppHandler
from jarvis.audit import MemoryAuditLog
from jarvis.brain.fake import FakeBrain
from jarvis.brain.mcp_bridge import JarvisToolBridge
from jarvis.core import CommandResult, handle_command
from jarvis.events import EventBus, StepFinished, StepStarted
from jarvis.spotify.fake import FakeSpotifyPlayer, sample_spotify
from jarvis.system.handler import SystemHandler
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import BrainTurn
from jarvis.windows.handler import WindowHandler
from jarvis.windows.win32api import WindowInfo

# Per-tier dispatch budgets (dispatch decision + local handler, fakes for
# cloud/OS). Reflex must be snappy; the fake brain path completes inline.
REFLEX_BUDGET_S = 1.0
BRAIN_BUDGET_S = 5.0


# --------------------------------------------------------------------------
# Harness: run one utterance through the real pipeline with fakes injected
# --------------------------------------------------------------------------


@dataclass
class PackRun:
    """Observable outcome of one acceptance run."""

    result: CommandResult
    tier: str | None  # audit path that answered: "system" / "windows" / "brain" …
    elapsed_s: float
    speaker: FakeSpeaker
    audit: MemoryAuditLog
    events: list[Any]

    @property
    def steps(self) -> list[tuple[str, str]]:
        """Ordered (event-name, tool-name) for bridge Step* events."""
        return [
            (type(e).__name__, e.name)
            for e in self.events
            if isinstance(e, (StepStarted, StepFinished))
        ]


def run_pack(
    utterance: str,
    *,
    brain: Any | None = None,
    bus: EventBus | None = None,
    **handlers: Any,
) -> PackRun:
    """Drive *utterance* through :func:`handle_command` and record the tier."""
    audit = MemoryAuditLog()
    speaker = FakeSpeaker()
    events: list[Any] = []
    if bus is not None:
        bus.subscribe(events.append)
    brain = brain if brain is not None else FakeBrain(script=[])

    t0 = time.perf_counter()
    result = handle_command(
        utterance, brain=brain, speaker=speaker, audit=audit, **handlers
    )
    elapsed = time.perf_counter() - t0

    handled = [e for e in audit.events if e["event"] == "command_handled"]
    tier = handled[-1]["path"] if handled else None
    return PackRun(
        result=result,
        tier=tier,
        elapsed_s=elapsed,
        speaker=speaker,
        audit=audit,
        events=events,
    )


@dataclass
class ScriptedBridgeBrain:
    """FakeBrain stand-in that drives the JARVIS tools like Claude would.

    ``script`` is an ordered list of ``(tool, plain-english-command)`` pairs;
    each is dispatched through the real in-process bridge, so we exercise the
    genuine confirm gate, Step* events and domain handlers — never real Claude.
    """

    bridge: JarvisToolBridge
    script: tuple[tuple[str, str], ...] = ()
    session_id: str | None = "sess-pack"
    tool_results: list[str] = field(default_factory=list)

    def ask(self, command: str, *, confirmed: bool = False) -> BrainTurn:
        replies: list[str] = []
        for tool, arg in self.script:
            res = self.bridge.call_tool(tool, {"command": arg})
            self.tool_results.append(res.text)
            replies.append(res.text)
        return BrainTurn(
            reply=" ".join(replies) or "Done.", session_id=self.session_id, ok=True
        )


# --------------------------------------------------------------------------
# Handler builders (hermetic fakes — no real Win32 / disk / display)
# --------------------------------------------------------------------------


def _apps(launches: list[str]) -> AppHandler:
    return AppHandler(
        ops={
            "find_windows": lambda **kw: [],
            "focus": lambda hwnd: None,
            "launch": lambda spec, force_new=False: launches.append(spec.key),
        }
    )


def _windows(
    *,
    minimize_all_count: int = 0,
    minimized_all: list[str] | None = None,
    closed: list[int] | None = None,
    snaps: list[str] | None = None,
    waited: list[dict[str, Any]] | None = None,
    resolve_via_wait: bool = False,
) -> WindowHandler:
    """A window handler whose every Win32 op is a recorder.

    ``resolve_via_wait`` makes ``find_windows`` return nothing so a snap has to
    resolve the target through ``wait_for_window`` — i.e. it must wait for the
    freshly-launched window to appear (the (e) window-wait).
    """

    def _find(**kw: Any) -> list[WindowInfo]:
        return []

    def _wait(**kw: Any) -> WindowInfo | None:
        if waited is not None:
            waited.append(dict(kw))
        name = str(kw.get("process") or kw.get("title_substr") or "win")
        return WindowInfo(hwnd=abs(hash(name)) % 100000, title=name, pid=1, process=name)

    def _minimize_all() -> int:
        if minimized_all is not None:
            minimized_all.append("all")
        return minimize_all_count

    def _close(hwnd: int) -> None:
        if closed is not None:
            closed.append(hwnd)

    def _snap(hwnd: int, side: str) -> None:
        if snaps is not None:
            snaps.append(side)

    return WindowHandler(
        ops={
            "find_windows": _find,
            "wait_for_window": _wait if resolve_via_wait else (lambda **kw: None),
            "minimize_all": _minimize_all,
            "close": _close,
            "snap_half": _snap,
            "focus": lambda hwnd: None,
            "minimize": lambda hwnd: None,
            "maximize": lambda hwnd: None,
            "restore": lambda hwnd: None,
        }
    )


def _system(
    capture_root: Path | None = None,
    *,
    opened: list[Path] | None = None,
    brightness_set: list[int] | None = None,
) -> SystemHandler:
    return SystemHandler(
        capture_roots=(capture_root,) if capture_root is not None else (),
        open_fn=(opened.append if opened is not None else (lambda p: None)),
        set_brightness=(
            brightness_set.append if brightness_set is not None else (lambda x: None)
        ),
        get_brightness=lambda: 50,
    )


def _capture_dir(tmp_path: Path) -> tuple[Path, Path]:
    """A capture folder with an older and a newest .mp4 (newest wins)."""
    older = tmp_path / "recording old.mp4"
    newest = tmp_path / "recording new.mp4"
    older.write_bytes(b"x")
    time.sleep(0.02)
    newest.write_bytes(b"x")
    import os

    base = time.time()
    os.utime(older, (base - 100, base - 100))
    os.utime(newest, (base, base))
    return tmp_path, newest


# ==========================================================================
# (a) "open the screen recording we just captured"
# ==========================================================================


def test_a_open_latest_recording_is_reflex(tmp_path: Path) -> None:
    """The canonical phrasing matches the latest-file reflex → system tier."""
    root, newest = _capture_dir(tmp_path)
    opened: list[Path] = []
    run = run_pack(
        "open the screen recording we just captured",
        system=_system(root, opened=opened),
        windows=_windows(),
    )

    assert run.tier == "system", f"expected reflex system tier, got {run.tier}"
    assert opened == [newest], "did not open the newest capture"
    assert any(
        a.name == "latest_capture_open" and str(newest) in a.detail
        for a in run.result.actions
    )
    assert run.result.ok and run.speaker.spoken
    assert run.elapsed_s < REFLEX_BUDGET_S, f"reflex too slow: {run.elapsed_s:.3f}s"


def test_a_paraphrase_falls_through_to_brain_bridge(tmp_path: Path) -> None:
    """A paraphrase the reflex regex misses is handled by the brain + bridge.

    The same system handler is wired both as the reflex tier (which declines —
    the regex misses) and behind the bridge, so when the brain calls the system
    tool it really opens the newest capture.
    """
    root, newest = _capture_dir(tmp_path)
    opened: list[Path] = []
    system = _system(root, opened=opened)

    bus = EventBus()
    bridge = JarvisToolBridge(bus=bus, system=system)
    brain = ScriptedBridgeBrain(
        bridge=bridge, script=(("system", "open the last screen recording"),)
    )

    run = run_pack(
        "show me what I just recorded off my screen",
        brain=brain,
        bus=bus,
        system=system,  # reflex tier declines (regex miss) → falls to brain
        windows=_windows(),
    )

    assert run.tier == "brain", f"paraphrase should reach the brain, got {run.tier}"
    assert opened == [newest], "bridge system tool did not open the newest capture"
    assert run.steps == [("StepStarted", "system"), ("StepFinished", "system")]
    assert run.result.ok and run.speaker.spoken
    assert not run.result.backgrounded, "fake brain path must not silently stall"
    assert run.elapsed_s < BRAIN_BUDGET_S


# ==========================================================================
# (b) "open spotify and play the next music" → brain + bridge, two steps
# ==========================================================================


def test_b_open_spotify_then_next_is_brain_bridge_two_steps() -> None:
    bus = EventBus()
    launches: list[str] = []
    player = FakeSpotifyPlayer()
    # The SAME handler instances back both the reflex chain and the bridge, so
    # this exercises genuine routing: the apps/spotify reflexes are really wired
    # and the compound guard must DECLINE them (else the apps reflex would grab
    # "spotify …" and launch Spotify only, dropping "play next").
    apps = _apps(launches)
    spotify = sample_spotify(player=player)
    bridge = JarvisToolBridge(bus=bus, apps=apps, spotify=spotify)
    brain = ScriptedBridgeBrain(
        bridge=bridge,
        script=(
            ("apps", "open spotify"),
            ("spotify", "play the next track"),
        ),
    )

    run = run_pack(
        "open spotify and play the next music",
        brain=brain,
        bus=bus,
        apps=apps,  # full reflex chain wired — guard declines → brain composes
        spotify=spotify,
    )

    assert run.tier == "brain", f"compound must reach the brain, got {run.tier}"
    # Both domains actually fired, in order.
    assert launches == ["spotify"], "apps.open did not launch Spotify"
    assert "next" in player.calls, "spotify.next did not skip the track"
    assert run.steps == [
        ("StepStarted", "apps"),
        ("StepFinished", "apps"),
        ("StepStarted", "spotify"),
        ("StepFinished", "spotify"),
    ], run.steps
    assert run.result.ok and run.speaker.spoken and run.result.reply.strip()
    assert not run.result.backgrounded
    assert run.elapsed_s < BRAIN_BUDGET_S


# ==========================================================================
# (c) "close all the windows" → MINIMIZE all (windows reflex); closes NOTHING
# ==========================================================================


def test_c_close_all_windows_minimizes_and_closes_nothing() -> None:
    minimized_all: list[str] = []
    closed: list[int] = []
    launches: list[str] = []
    run = run_pack(
        "close all the windows",
        windows=_windows(
            minimize_all_count=4, minimized_all=minimized_all, closed=closed
        ),
        apps=_apps(launches),  # prove nothing gets opened/closed as an app either
    )

    assert run.tier == "windows", f"expected windows reflex, got {run.tier}"
    assert minimized_all == ["all"], "minimize-all did not fire"
    assert any(
        a.name == "window_minimize_all" for a in run.result.actions
    ), run.result.actions
    # Nothing was closed — not a window, not an app/process.
    assert closed == [], "a window was closed (must only minimize)"
    assert launches == []
    closing = {"window_close", "close_app", "close", "app_launch"}
    assert not any(a.name in closing for a in run.result.actions), run.result.actions
    assert "minimize" in run.result.reply.lower()
    assert run.result.ok and run.speaker.spoken
    assert run.elapsed_s < REFLEX_BUDGET_S


# ==========================================================================
# (d) "dim my brightness to zero" → reflex (system)
# ==========================================================================


def test_d_dim_brightness_to_zero_is_reflex() -> None:
    brightness_set: list[int] = []
    run = run_pack(
        "dim my brightness to zero",
        system=_system(brightness_set=brightness_set),
        windows=_windows(),
    )

    assert run.tier == "system", f"expected reflex system tier, got {run.tier}"
    assert brightness_set == [0], "brightness was not set to 0"
    assert any(
        a.name == "brightness_set" and a.detail == "0" for a in run.result.actions
    )
    assert run.result.ok and run.speaker.spoken
    assert run.elapsed_s < REFLEX_BUDGET_S


# ==========================================================================
# (e) "open brave and vs code side by side, brave left 50%, vs code right"
#     → brain + bridge: launch both, wait for windows, snap left then right
# ==========================================================================


def test_e_side_by_side_launches_waits_and_snaps_in_order() -> None:
    bus = EventBus()
    launches: list[str] = []
    snaps: list[str] = []
    waited: list[dict[str, Any]] = []
    windows = _windows(snaps=snaps, waited=waited, resolve_via_wait=True)
    # SAME handlers back the reflex chain and the bridge (genuine routing): with
    # the reflexes wired, the apps reflex would otherwise grab "brave and vs code
    # …" and open Brave only. The compound guard ("side by side") must decline.
    apps = _apps(launches)
    bridge = JarvisToolBridge(bus=bus, apps=apps, windows=windows)
    brain = ScriptedBridgeBrain(
        bridge=bridge,
        script=(
            ("apps", "open brave"),
            ("apps", "open vs code"),
            ("windows", "snap brave to the left half"),
            ("windows", "snap vs code to the right half"),
        ),
    )

    run = run_pack(
        "open brave and vs code side by side, brave left 50%, vs code right",
        brain=brain,
        bus=bus,
        apps=apps,  # full reflex chain wired — guard declines → brain composes
        windows=windows,
    )

    assert run.tier == "brain", f"expected brain + bridge, got {run.tier}"
    # Both apps launched.
    assert launches == ["brave", "code"], launches
    # Windows were waited for before snapping (freshly-launched → resolve via wait).
    assert len(waited) >= 2, f"window-wait not observed: {waited}"
    # Snap left then right, in order.
    assert snaps == ["left", "right"], snaps
    # Bridge Step order: two app opens, then two snaps.
    assert run.steps == [
        ("StepStarted", "apps"),
        ("StepFinished", "apps"),
        ("StepStarted", "apps"),
        ("StepFinished", "apps"),
        ("StepStarted", "windows"),
        ("StepFinished", "windows"),
        ("StepStarted", "windows"),
        ("StepFinished", "windows"),
    ], run.steps
    assert run.result.ok and run.speaker.spoken
    assert not run.result.backgrounded
    assert run.elapsed_s < BRAIN_BUDGET_S


# ==========================================================================
# (c) idiom guard: the minimize mapping must not swallow a real single-close
# ==========================================================================


def test_c_idiom_does_not_break_single_window_close() -> None:
    """The close-all idiom is tight: "close chrome" still closes one window."""
    from jarvis.windows.intents import WindowIntentKind, classify

    assert classify("close all the windows").kind is WindowIntentKind.MINIMIZE_ALL
    assert classify("close all windows").kind is WindowIntentKind.MINIMIZE_ALL
    assert classify("close every window").kind is WindowIntentKind.MINIMIZE_ALL
    # Single-window close is untouched.
    assert classify("close chrome").kind is WindowIntentKind.CLOSE
    assert classify("close notepad").kind is WindowIntentKind.CLOSE
    assert classify("close this window").kind is WindowIntentKind.CLOSE


# ==========================================================================
# Compound guard (issue 17 gap): both sides through the REAL stack
# ==========================================================================


class _Offline:
    def is_online(self) -> bool:
        return False


def test_compound_single_open_still_hits_apps_reflex() -> None:
    """The guard is one-sided: a plain "open spotify" is NOT compound, so the
    apps reflex still owns it — the brain must not be involved."""
    launches: list[str] = []
    run = run_pack(
        "open spotify",
        brain=FakeBrain(script=[]),  # empty script → raises if the brain runs
        apps=_apps(launches),
    )
    assert run.tier == "apps", f"single open must stay reflex, got {run.tier}"
    assert launches == ["spotify"]
    assert run.elapsed_s < REFLEX_BUDGET_S


def test_compound_offline_degrades_without_half_executing() -> None:
    """Offline, a compound command reaches the brain gate and degrades to
    BRAIN_UNREACHABLE — the apps reflex must never fire the first clause."""
    launches: list[str] = []
    run = run_pack(
        "open spotify and play the next music",
        brain=FakeBrain(script=[]),
        apps=_apps(launches),
        connectivity=_Offline(),
    )
    assert run.tier == "brain", f"expected brain gate, got {run.tier}"
    assert run.result.error == "brain_unreachable"
    assert not run.result.ok
    assert launches == [], "reflex half-executed a compound command offline"
