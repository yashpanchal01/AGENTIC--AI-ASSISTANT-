"""Unit tests for the perception tools (issue 19) — no Claude, no real OS.

Covers the Observer senses against fake adapters (shape, sorting, caps,
filters, truncation), the bridge's structured-arg dispatch for the four
observe_* tools (no confirm gate, Step* events, audit records), observe_music
honesty (configured vs not set up), and the two-step observe→act flow for
"open the movie I downloaded last night".
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.audit import MemoryAuditLog, attach_audit
from jarvis.brain.mcp_bridge import JarvisToolBridge
from jarvis.confirm import FixedConfirmer
from jarvis.core import handle_command
from jarvis.events import EventBus, StepFailed, StepFinished, StepStarted
from jarvis.media.handler import LocalMediaHandler
from jarvis.perception import (
    MAX_ROWS,
    TITLE_MAX,
    FileObs,
    Observer,
    ProcessObs,
    WindowObs,
    default_scan_files,
)
from jarvis.spotify.controller import NOT_CONFIGURED_REPLY
from jarvis.spotify.fake import FakeSpotifyPlayer, sample_spotify
from jarvis.tts.fake import FakeSpeaker
from jarvis.types import BrainTurn


def _win(
    title: str,
    process: str = "app",
    pid: int = 1,
    *,
    minimized: bool = False,
    focused: bool = False,
) -> WindowObs:
    return WindowObs(
        title=title, process=process, pid=pid, minimized=minimized, focused=focused
    )


def _observer(**kw: Any) -> Observer:
    kw.setdefault("named_roots", {})
    kw.setdefault("approved_roots", ())
    kw.setdefault("list_windows", lambda: [])
    kw.setdefault("list_processes", lambda: [])
    kw.setdefault("scan_files", lambda root: [])
    return Observer(**kw)


def _bus_with_log() -> tuple[EventBus, list[object]]:
    bus = EventBus()
    events: list[object] = []
    bus.subscribe(events.append)
    return bus, events


# --- observe_windows ---------------------------------------------------------


def test_windows_focused_first_with_flags_and_pids() -> None:
    obs = _observer(
        list_windows=lambda: [
            _win("Notes", "notepad", 11, minimized=True),
            _win("Google Chrome", "chrome", 22, focused=True),
            _win("VLC media player", "vlc", 33),
        ]
    )
    result = obs.observe_windows()
    lines = result.reply.splitlines()
    assert result.ok and result.rows == 3
    assert lines[0] == "3 open windows:"
    assert lines[1] == "- chrome (pid 22) [focused]: Google Chrome"
    assert "[minimized]" in result.reply
    assert "- vlc (pid 33): VLC media player" in lines


def test_windows_process_and_title_filters() -> None:
    obs = _observer(
        list_windows=lambda: [
            _win("Google Chrome - stack overflow", "chrome", 1),
            _win("Google Chrome - gmail", "chrome", 2),
            _win("Notes", "notepad", 3),
        ]
    )
    by_proc = obs.observe_windows(process="chrome")
    assert by_proc.rows == 2 and "Notes" not in by_proc.reply
    by_title = obs.observe_windows(title="GMAIL")
    assert by_title.rows == 1 and "gmail" in by_title.reply
    none = obs.observe_windows(process="firefox")
    assert none.rows == 0 and none.reply == "No open windows matched."
    assert none.ok  # seeing nothing is a successful observation


def test_windows_capped_at_max_rows_and_titles_truncated() -> None:
    long_title = "x" * (TITLE_MAX + 40)
    obs = _observer(
        list_windows=lambda: [_win(long_title, "app", i) for i in range(40)]
    )
    result = obs.observe_windows()
    lines = result.reply.splitlines()
    assert result.rows == MAX_ROWS
    assert lines[0] == f"40 open windows (showing top {MAX_ROWS}):"
    assert len(lines) == 1 + MAX_ROWS
    assert all(line.endswith("…") for line in lines[1:])
    title_part = lines[1].split(": ", 1)[1]
    assert len(title_part) <= TITLE_MAX


# --- observe_processes -------------------------------------------------------


def test_processes_sorted_by_ram_desc_with_readable_sizes() -> None:
    obs = _observer(
        list_processes=lambda: [
            ProcessObs("chrome.exe", 100, ram_kb=512_000),
            ProcessObs("python.exe", 200, ram_kb=2_097_152),  # 2 GB
            ProcessObs("notepad.exe", 300, ram_kb=10_240),
        ]
    )
    result = obs.observe_processes()
    lines = result.reply.splitlines()
    assert lines[0] == "3 processes by RAM:"
    assert lines[1] == "- python.exe (pid 200): 2.0 GB"
    assert lines[2] == "- chrome.exe (pid 100): 500 MB"
    assert lines[3] == "- notepad.exe (pid 300): 10 MB"


def test_processes_name_filter_and_limit() -> None:
    procs = [ProcessObs(f"proc{i}.exe", i, ram_kb=i * 1000) for i in range(1, 40)]
    procs.append(ProcessObs("chrome.exe", 999, ram_kb=5))
    obs = _observer(list_processes=lambda: procs)

    filtered = obs.observe_processes(name="CHROME")
    assert filtered.rows == 1 and "chrome.exe (pid 999)" in filtered.reply

    limited = obs.observe_processes(limit=3)
    assert limited.rows == 3
    assert limited.reply.splitlines()[0] == "40 processes by RAM (showing top 3):"

    capped = obs.observe_processes(limit=999)  # never above the hard cap
    assert capped.rows == MAX_ROWS

    empty = obs.observe_processes(name="nothing-matches")
    assert empty.rows == 0 and empty.reply == "No running processes matched."


# --- observe_files -----------------------------------------------------------


def _touch(path: Path, *, mtime: float, size: int = 3) -> None:
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))


def test_files_newest_first_with_ext_filter_and_limit(tmp_path: Path) -> None:
    _touch(tmp_path / "old movie.mp4", mtime=1_000_000, size=2048)
    _touch(tmp_path / "new movie.mp4", mtime=2_000_000, size=4096)
    _touch(tmp_path / "notes.txt", mtime=3_000_000)
    obs = _observer(named_roots={"downloads": tmp_path}, scan_files=default_scan_files)

    result = obs.observe_files(folder="downloads", ext="mp4")
    lines = result.reply.splitlines()
    assert result.ok and result.rows == 2
    assert lines[0] == "2 files in downloads, newest first:"
    assert lines[1].startswith("- new movie.mp4 (4 KB, ")
    assert lines[2].startswith("- old movie.mp4 (2 KB, ")
    assert "notes.txt" not in result.reply

    limited = obs.observe_files(folder="Downloads", limit=1)  # name is case-blind
    assert limited.rows == 1 and "notes.txt" in limited.reply  # newest overall


def test_files_empty_folder_is_honest_not_an_error(tmp_path: Path) -> None:
    obs = _observer(named_roots={"downloads": tmp_path}, scan_files=default_scan_files)
    result = obs.observe_files(folder="downloads")
    assert result.ok and result.rows == 0
    assert result.reply == "No files found in downloads."


def test_files_unknown_folder_word_is_refused_plainly() -> None:
    obs = _observer(named_roots={"downloads": Path("X:/nope")})
    result = obs.observe_files(folder="secrets")
    assert result.ok is False and result.error == "unknown_folder"
    assert "downloads" in result.reply


def test_files_path_outside_approved_folders_is_refused(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    _touch(approved / "a.txt", mtime=1_000_000)
    obs = _observer(approved_roots=(approved,), scan_files=default_scan_files)

    denied = obs.observe_files(folder=str(outside))
    assert denied.ok is False and denied.error == "folder_not_allowed"
    assert "approved" in denied.reply

    allowed = obs.observe_files(folder=str(approved))
    assert allowed.ok and allowed.rows == 1 and "a.txt" in allowed.reply


def test_default_scan_files_missing_folder_is_empty(tmp_path: Path) -> None:
    assert default_scan_files(tmp_path / "does-not-exist") == []


# --- bridge dispatch (structured args, no confirm gate, audit) ---------------


@dataclass
class RecordingObserver:
    """Args-inspection fake: records every kwarg the bridge routes through."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    fail: bool = False

    def _obs(self, sense: str, kwargs: dict[str, Any]):
        from jarvis.perception import Observation

        self.calls.append((sense, kwargs))
        if self.fail:
            raise RuntimeError("kaboom")
        return Observation(reply=f"{sense} ok", rows=1)

    def observe_windows(self, **kw):
        return self._obs("windows", kw)

    def observe_processes(self, **kw):
        return self._obs("processes", kw)

    def observe_files(self, **kw):
        return self._obs("files", kw)


def test_bridge_routes_structured_args_without_confirm_gate() -> None:
    bus, events = _bus_with_log()
    observer = RecordingObserver()
    confirmer = FixedConfirmer(answer=False)  # would cancel if ever consulted
    bridge = JarvisToolBridge(bus=bus, confirmer=confirmer, observer=observer)

    res = bridge.call_tool(
        "observe_files", {"folder": "downloads", "ext": ".mp4", "limit": 5}
    )

    assert res.is_error is False and res.text == "files ok"
    assert observer.calls == [
        ("files", {"folder": "downloads", "ext": ".mp4", "limit": 5})
    ]
    assert not confirmer.calls, "read-only observe must never ask for confirmation"
    assert [type(e) for e in events if isinstance(e, (StepStarted, StepFinished))] == [
        StepStarted,
        StepFinished,
    ]
    assert events[0].name == "observe_files"
    assert "folder=downloads" in events[0].detail


def test_bridge_routes_window_and_process_filters() -> None:
    observer = RecordingObserver()
    bridge = JarvisToolBridge(bus=EventBus(), observer=observer)

    bridge.call_tool("observe_windows", {"process": "chrome", "title": "mail"})
    bridge.call_tool("observe_processes", {"name": "python", "limit": "3"})

    assert observer.calls == [
        ("windows", {"process": "chrome", "title": "mail"}),
        ("processes", {"name": "python", "limit": 3}),  # string limit coerced
    ]


def test_bridge_observe_writes_audit_records() -> None:
    bus = EventBus()
    audit = MemoryAuditLog()
    attach_audit(bus, audit)
    bridge = JarvisToolBridge(bus=bus, observer=RecordingObserver())

    bridge.call_tool("observe_windows", {"process": "vlc"})

    records = [e for e in audit.events if e["event"] == "observe"]
    assert len(records) == 1
    assert records[0]["tool"] == "observe_windows"
    assert records[0]["args"] == {"process": "vlc"}
    assert records[0]["ok"] is True and records[0]["rows"] == 1


def test_bridge_observe_adapter_failure_speaks_plainly_and_audits() -> None:
    bus, events = _bus_with_log()
    audit = MemoryAuditLog()
    attach_audit(bus, audit)
    bridge = JarvisToolBridge(bus=bus, observer=RecordingObserver(fail=True))

    res = bridge.call_tool("observe_processes", {})

    assert res.is_error is True and res.error == "RuntimeError"
    assert "kaboom" not in res.text and "Traceback" not in res.text
    assert isinstance(events[-1], StepFailed)
    records = [e for e in audit.events if e["event"] == "observe"]
    assert records and records[0]["ok"] is False


def test_bridge_observe_without_observer_is_unavailable() -> None:
    bus, events = _bus_with_log()
    bridge = JarvisToolBridge(bus=bus, observer=None)
    res = bridge.call_tool("observe_windows", {})
    assert res.is_error is True and res.error == "unavailable"
    assert isinstance(events[-1], StepFailed)


def test_bridge_jsonrpc_tools_call_routes_observe_args() -> None:
    observer = RecordingObserver()
    bridge = JarvisToolBridge(bus=EventBus(), observer=observer)
    resp = bridge.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "observe_processes",
                "arguments": {"name": "chrome", "limit": 2},
            },
        }
    )
    assert resp["result"]["isError"] is False
    assert resp["result"]["content"][0]["text"] == "processes ok"
    assert observer.calls == [("processes", {"name": "chrome", "limit": 2})]


# --- observe_music -----------------------------------------------------------


def test_observe_music_reports_now_playing_when_configured() -> None:
    bus, events = _bus_with_log()
    player = FakeSpotifyPlayer()
    bridge = JarvisToolBridge(bus=bus, spotify=sample_spotify(player=player))

    res = bridge.call_tool("observe_music", {})

    assert res.is_error is False
    assert "Midnight City" in res.text and "M83" in res.text
    assert "now_playing" in player.calls
    assert isinstance(events[-1], StepFinished)


def test_observe_music_unconfigured_speaks_honest_not_set_up() -> None:
    bus, events = _bus_with_log()
    bridge = JarvisToolBridge(bus=bus, spotify=sample_spotify(configured=False))

    res = bridge.call_tool("observe_music", {})

    assert res.is_error is True and res.error == "not_configured"
    assert res.text == NOT_CONFIGURED_REPLY
    assert isinstance(events[-1], StepFailed)


def test_observe_music_without_spotify_is_unavailable() -> None:
    bridge = JarvisToolBridge(bus=EventBus(), spotify=None)
    res = bridge.call_tool("observe_music", {})
    assert res.is_error is True and res.error == "unavailable"


# --- two-step observe → act ("the movie I downloaded last night") -------------


@dataclass
class ObserveThenActBrain:
    """Fake brain: observes downloads like Claude would, then acts on the
    newest file it read out of the observation text."""

    bridge: JarvisToolBridge
    session_id: str | None = "sess-observe"
    observed: str = ""

    def ask(self, command: str, *, confirmed: bool = False) -> BrainTurn:
        obs = self.bridge.call_tool(
            "observe_files", {"folder": "downloads", "ext": ".mp4"}
        )
        self.observed = obs.text
        # "Read" the newest row: "- <name> (<size>, <mtime>)" on line 2.
        newest = obs.text.splitlines()[1].removeprefix("- ").rsplit(" (", 1)[0]
        act = self.bridge.call_tool(
            "media", {"command": f"play the movie {Path(newest).stem}"}
        )
        return BrainTurn(reply=act.text, session_id=self.session_id, ok=True)


def test_open_last_nights_movie_observe_then_act(tmp_path: Path) -> None:
    _touch(tmp_path / "old episode.mp4", mtime=1_000_000)
    _touch(tmp_path / "Interstellar.mp4", mtime=2_000_000)
    bus, events = _bus_with_log()
    opened: list[Path] = []
    bridge = JarvisToolBridge(
        bus=bus,
        observer=_observer(
            named_roots={"downloads": tmp_path}, scan_files=default_scan_files
        ),
        media=LocalMediaHandler(roots=(tmp_path,), open_fn=opened.append),
    )
    brain = ObserveThenActBrain(bridge=bridge)
    speaker = FakeSpeaker()

    result = handle_command(
        "open the movie I downloaded last night", brain=brain, speaker=speaker
    )

    # The observation surfaced the newest download, and the act opened IT.
    assert "Interstellar.mp4" in brain.observed
    assert opened == [tmp_path / "Interstellar.mp4"]
    steps = [
        (type(e).__name__, e.name)
        for e in events
        if isinstance(e, (StepStarted, StepFinished))
    ]
    assert steps == [
        ("StepStarted", "observe_files"),
        ("StepFinished", "observe_files"),
        ("StepStarted", "media"),
        ("StepFinished", "media"),
    ]
    assert result.ok and speaker.spoken
