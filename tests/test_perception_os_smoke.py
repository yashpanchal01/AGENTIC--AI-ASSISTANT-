"""Opt-in real-OS perception smoke (issue 19): ``pytest -m os_smoke``.

Deselected automatically in the default run (see addopts in pyproject.toml).
These really enumerate this desktop's windows via EnumWindows, read the live
process list via tasklist, and list the user's actual Downloads folder —
read-only throughout, so nothing to clean up.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from jarvis.perception import (
    MAX_ROWS,
    Observer,
    default_list_processes,
    default_list_windows,
)

pytestmark = [
    pytest.mark.os_smoke,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows-only"),
]


def test_real_observe_windows_lists_this_desktop() -> None:
    """Real EnumWindows sees this session's own console/IDE windows."""
    wins = default_list_windows()
    assert wins, "EnumWindows returned no visible titled windows"
    assert all(w.pid > 0 for w in wins)
    assert any(w.title and w.process for w in wins), "no window had title+process"

    obs = Observer().observe_windows()
    assert obs.ok and 1 <= obs.rows <= MAX_ROWS
    lines = obs.reply.splitlines()
    assert lines[0].startswith(f"{len(wins)} open windows")
    assert all(line.startswith("- ") for line in lines[1:])


def test_real_observe_processes_includes_python_sorted_desc() -> None:
    """Real tasklist sees this very pytest process, with real RAM numbers."""
    procs = default_list_processes()
    assert len(procs) > 20, "suspiciously few processes for a live Win11 session"
    me = [p for p in procs if "python" in p.name.lower()]
    assert me, "the running python.exe is missing from tasklist output"
    assert any(p.ram_kb > 10_000 for p in me), "python RAM implausibly small"

    obs = Observer().observe_processes()
    assert obs.ok and obs.rows == min(MAX_ROWS, len(procs))
    # Sorted descending: the shown top consumer has the max RAM of them all.
    top = max(p.ram_kb for p in procs)
    first = obs.reply.splitlines()[1]
    assert f"(pid {next(p.pid for p in procs if p.ram_kb == top)})" in first

    filtered = Observer().observe_processes(name="python")
    assert filtered.ok and filtered.rows >= 1
    assert "python" in filtered.reply.lower()


def test_real_downloads_listing_on_this_machine() -> None:
    """The named 'downloads' root resolves and lists honestly (even if empty)."""
    downloads = Path.home() / "Downloads"
    assert downloads.is_dir(), "no Downloads folder on this machine"
    obs = Observer().observe_files(folder="downloads")
    assert obs.ok
    if obs.rows:
        assert obs.rows <= MAX_ROWS
        assert "files in downloads, newest first" in obs.reply.splitlines()[0]
    else:
        assert obs.reply == "No files found in downloads."


def test_real_approved_path_listing_newest_first(tmp_path: Path) -> None:
    """A real (temp) approved-folder path lists newest-first with real stats."""
    old = tmp_path / "old.mp4"
    new = tmp_path / "new.mp4"
    old.write_bytes(b"x" * 10)
    new.write_bytes(b"y" * 10)
    os.utime(old, (1_000_000, 1_000_000))

    obs = Observer(approved_roots=(tmp_path,)).observe_files(
        folder=str(tmp_path), ext=".mp4"
    )
    assert obs.ok and obs.rows == 2
    lines = obs.reply.splitlines()
    assert lines[1].startswith("- new.mp4 ")
    assert lines[2].startswith("- old.mp4 ")
