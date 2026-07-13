"""System controls (issue 16): brightness + latest-capture resolver.

Unit coverage only — the real WMI call and real file open are exercised by the
opt-in ``os_smoke`` marker in ``test_os_smoke.py``. Here the WMI wrapper and the
OS open are FAKED so the default suite never touches the real display or disk.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from jarvis.audit import MemoryAuditLog
from jarvis.brain.fake import FakeBrain
from jarvis.core import handle_command
from jarvis.plain_replies import BRIGHTNESS_UNSUPPORTED
from jarvis.settings import parse_settings_dict
from jarvis.system.brightness import BrightnessError, clamp
from jarvis.system.handler import SystemHandler, find_latest
from jarvis.system.intents import SystemIntentKind, classify
from jarvis.tts.fake import FakeSpeaker


# --------------------------------------------------------------------------
# Intent parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "utterance,level",
    [
        ("dim my brightness to zero", 0),
        ("set brightness to 50", 50),
        ("brightness to max", 100),
        ("set the brightness to 100 percent", 100),
        ("brightness at 30%", 30),
        ("set brightness to half", 50),
    ],
)
def test_brightness_set_parsing(utterance: str, level: int) -> None:
    intent = classify(utterance)
    assert intent.kind is SystemIntentKind.BRIGHTNESS_SET
    assert intent.level == level


@pytest.mark.parametrize(
    "utterance,sign",
    [
        ("turn the brightness up", +1),
        ("brighten the screen", +1),
        ("raise brightness", +1),
        ("turn brightness down", -1),
        ("dim the screen", -1),
        ("lower the brightness", -1),
    ],
)
def test_brightness_step_parsing(utterance: str, sign: int) -> None:
    intent = classify(utterance)
    assert intent.kind is SystemIntentKind.BRIGHTNESS_STEP
    assert intent.delta is not None
    assert (intent.delta > 0) == (sign > 0)


def test_non_brightness_is_unrelated() -> None:
    assert classify("open notepad").kind is SystemIntentKind.UNRELATED
    assert classify("what's the weather").kind is SystemIntentKind.UNRELATED
    # "brightness" alone is not actionable.
    assert classify("brightness").kind is SystemIntentKind.UNRELATED


# --------------------------------------------------------------------------
# Brightness — WMI wrapper faked (set path + unsupported-panel error path)
# --------------------------------------------------------------------------


def _handler(**kw) -> SystemHandler:
    return SystemHandler(capture_roots=(), open_fn=lambda p: None, **kw)


def test_brightness_set_calls_wmi_with_clamped_level() -> None:
    calls: list[int] = []
    h = _handler(set_brightness=calls.append)

    res = h.try_handle("set brightness to 50")

    assert res is not None and res.ok
    assert calls == [50]
    assert "50" in res.reply
    assert any(a.name == "brightness_set" and a.detail == "50" for a in res.actions)


def test_brightness_zero_maps_to_zero() -> None:
    calls: list[int] = []
    res = _handler(set_brightness=calls.append).try_handle("dim brightness to zero")
    assert res is not None and res.ok
    assert calls == [0]


def test_brightness_step_reads_then_sets() -> None:
    calls: list[int] = []
    h = _handler(get_brightness=lambda: 40, set_brightness=calls.append)

    up = h.try_handle("turn the brightness up")
    down = h.try_handle("turn the brightness down")

    assert up is not None and up.ok and calls[0] == 60  # 40 + 20
    assert down is not None and down.ok and calls[1] == 20  # 40 - 20


def test_brightness_step_clamps_at_bounds() -> None:
    calls: list[int] = []
    h = _handler(get_brightness=lambda: 95, set_brightness=calls.append)
    res = h.try_handle("turn the brightness up")
    assert res is not None and res.ok
    assert calls == [100]  # 95 + 20 clamped to 100


def test_unsupported_panel_speaks_plain_no_crash() -> None:
    """A panel without WMI brightness → plain spoken line, ok=False, no raise."""

    def _boom(_level: int) -> None:
        raise BrightnessError(BRIGHTNESS_UNSUPPORTED)

    res = _handler(set_brightness=_boom).try_handle("set brightness to 50")

    assert res is not None
    assert res.ok is False
    assert res.error == "brightness_unsupported"
    assert res.reply == BRIGHTNESS_UNSUPPORTED


def test_unsupported_panel_step_path_also_plain() -> None:
    def _boom() -> int:
        raise BrightnessError(BRIGHTNESS_UNSUPPORTED)

    res = _handler(get_brightness=_boom).try_handle("turn the brightness up")
    assert res is not None and res.ok is False
    assert res.reply == BRIGHTNESS_UNSUPPORTED


def test_clamp_bounds() -> None:
    assert clamp(-5) == 0
    assert clamp(250) == 100
    assert clamp(50) == 50


# --------------------------------------------------------------------------
# Latest-capture resolver — temp folder tree
# --------------------------------------------------------------------------


def _touch(path: Path, mtime: float) -> Path:
    path.write_bytes(b"x")
    import os

    os.utime(path, (mtime, mtime))
    return path


def test_latest_capture_newest_by_mtime_wins(tmp_path: Path) -> None:
    base = time.time()
    _touch(tmp_path / "old.mp4", base - 300)
    newest = _touch(tmp_path / "new.mp4", base - 10)
    _touch(tmp_path / "middle.mkv", base - 100)

    opened: list[Path] = []
    h = SystemHandler(capture_roots=(tmp_path,), open_fn=opened.append)

    res = h.try_handle("open the last screen recording")

    assert res is not None and res.ok
    assert opened == [newest]
    assert "new.mp4" in res.reply
    assert any(a.name == "latest_capture_open" for a in res.actions)


def test_latest_capture_extension_filtering(tmp_path: Path) -> None:
    base = time.time()
    # A newer non-video file must be ignored; the older .mp4 wins.
    video = _touch(tmp_path / "clip.mp4", base - 100)
    _touch(tmp_path / "notes.txt", base - 1)
    _touch(tmp_path / "photo.png", base - 1)

    assert find_latest((tmp_path,), SystemHandler.capture_exts) == video

    opened: list[Path] = []
    res = SystemHandler(
        capture_roots=(tmp_path,), open_fn=opened.append
    ).try_handle("open the latest screen recording")
    assert res is not None and res.ok
    assert opened == [video]


def test_latest_capture_empty_folder_plain_explanation(tmp_path: Path) -> None:
    res = SystemHandler(
        capture_roots=(tmp_path,), open_fn=lambda p: None
    ).try_handle("open the last screen recording")
    assert res is not None
    assert res.ok is False
    assert res.error == "not_found"
    assert "couldn't find" in res.reply.lower()


def test_latest_capture_missing_folder_plain_explanation(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    res = SystemHandler(
        capture_roots=(missing,), open_fn=lambda p: None
    ).try_handle("open the last screen recording")
    assert res is not None and res.ok is False
    assert res.error == "not_found"


# --------------------------------------------------------------------------
# End-to-end through the core loop + audit log (regression)
# --------------------------------------------------------------------------


def _run(utterance: str, handler: SystemHandler, audit: MemoryAuditLog):
    return handle_command(
        utterance,
        brain=FakeBrain(),
        speaker=FakeSpeaker(),
        system=handler,
        audit=audit,
    )


def test_core_routes_brightness_and_audits() -> None:
    calls: list[int] = []
    audit = MemoryAuditLog()
    res = _run("set brightness to 50", _handler(set_brightness=calls.append), audit)

    assert res.ok and calls == [50]
    # Audit records the system path (both command_received + command_handled).
    handled = [e for e in audit.events if e["event"] == "command_handled"]
    assert handled and handled[-1]["path"] == "system"
    assert any(
        a.get("name") == "brightness_set" for a in handled[-1]["actions"]
    )


def test_core_routes_latest_capture_and_audits(tmp_path: Path) -> None:
    newest = _touch(tmp_path / "rec.mp4", time.time())
    opened: list[Path] = []
    audit = MemoryAuditLog()
    h = SystemHandler(capture_roots=(tmp_path,), open_fn=opened.append)

    res = _run("open the last screen recording", h, audit)

    assert res.ok and opened == [newest]
    handled = [e for e in audit.events if e["event"] == "command_handled"]
    assert handled[-1]["path"] == "system"


def test_core_falls_through_when_unrelated() -> None:
    """A non-system command returns None from the handler → reaches the brain."""
    audit = MemoryAuditLog()
    res = _run("tell me a joke", _handler(set_brightness=lambda x: None), audit)
    handled = [e for e in audit.events if e["event"] == "command_handled"]
    # FakeBrain answered — path is 'brain', not 'system'.
    assert handled[-1]["path"] == "brain"


# --------------------------------------------------------------------------
# Settings — capture folders configurable without code edits
# --------------------------------------------------------------------------


def test_capture_folders_from_settings_dict() -> None:
    s = parse_settings_dict(
        {"capture_folders": ["C:\\Users\\Me\\Videos\\Captures", "D:\\Clips"]}
    )
    assert s.capture_folders is not None
    assert Path("C:\\Users\\Me\\Videos\\Captures") in s.capture_folders
    assert Path("D:\\Clips") in s.capture_folders


def test_capture_folders_single_string() -> None:
    s = parse_settings_dict({"capture_folders": "C:\\Clips"})
    assert s.capture_folders == (Path("C:\\Clips"),)
