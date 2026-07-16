"""Opt-in real-OS hands smoke (issue 21): ``pytest -m os_smoke``.

Deselected automatically in the default run (see addopts in pyproject.toml).
These really spawn PowerShell for one read-only command and really zip +
recycle-delete files — but only inside a pytest temp folder registered as an
approved root, so nothing of the user's is touched and the only leftover is
a recycled temp file.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

from jarvis.brain.mcp_bridge import JarvisToolBridge
from jarvis.confirm import FixedConfirmer
from jarvis.events import EventBus
from jarvis.hands import Hands

pytestmark = [
    pytest.mark.os_smoke,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows-only"),
]


def test_real_run_command_git_version(tmp_path: Path) -> None:
    """One real allow-tier command end-to-end: no confirm, real output back."""
    confirmer = FixedConfirmer(answer=False)  # would cancel if ever consulted
    bridge = JarvisToolBridge(
        bus=EventBus(), confirmer=confirmer, hands=Hands(cwd=tmp_path)
    )

    res = bridge.call_tool("run_command", {"command": "git --version"})

    assert res.is_error is False, res.text
    assert res.text.startswith("exit 0")
    assert "git version" in res.text
    assert not confirmer.calls, "git --version is read-only; it must not ask"


def test_real_zip_then_recycle_delete_round_trip(tmp_path: Path) -> None:
    """Real zip (auto-allow) then real delete to the Recycle Bin (confirmed)."""
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / "a.txt").write_text("alpha", encoding="utf-8")
    (clips / "b.txt").write_text("beta", encoding="utf-8")
    archive = tmp_path / "clips.zip"
    confirmer = FixedConfirmer(answer=True)
    bridge = JarvisToolBridge(
        bus=EventBus(), confirmer=confirmer, hands=Hands(roots=(tmp_path,))
    )

    zipped = bridge.call_tool(
        "file_op", {"op": "zip", "src": str(clips), "dst": str(archive)}
    )
    assert zipped.is_error is False, zipped.text
    assert not confirmer.calls, "zip into an approved folder must not ask"
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == ["a.txt", "b.txt"]

    victim = clips / "a.txt"
    deleted = bridge.call_tool("file_op", {"op": "delete", "src": str(victim)})
    assert deleted.is_error is False, deleted.text
    assert "Recycle Bin" in deleted.text
    assert confirmer.calls and "a.txt" in confirmer.calls[0][1]
    # SHFileOperationW reported success and the path is really gone (recycled,
    # not hard-deleted — FOF_ALLOWUNDO); the sibling file is untouched.
    assert not victim.exists()
    assert (clips / "b.txt").exists()
