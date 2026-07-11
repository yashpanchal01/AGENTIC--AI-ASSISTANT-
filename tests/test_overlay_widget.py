"""Qt-level checks for the Aurora overlay (flags + screenshot harness).

Skipped automatically when PySide6 is not installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtCore, QtWidgets  # noqa: E402

from jarvis.overlay.aurora import AuroraOverlay, shoot_overlay_states  # noqa: E402
from jarvis.overlay.states import OverlayState  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_overlay_never_steals_focus(qapp) -> None:
    w = AuroraOverlay()
    flags = w.windowFlags()
    assert flags & QtCore.Qt.WindowDoesNotAcceptFocus
    assert flags & QtCore.Qt.WindowTransparentForInput
    assert flags & QtCore.Qt.WindowStaysOnTopHint
    assert flags & QtCore.Qt.FramelessWindowHint
    assert flags & QtCore.Qt.Tool
    assert w.testAttribute(QtCore.Qt.WA_ShowWithoutActivating)
    assert w.focusPolicy() == QtCore.Qt.NoFocus
    w.close()


def test_force_settles_active_states(qapp) -> None:
    w = AuroraOverlay()
    w.timer.stop()
    w.force(OverlayState.HEARD, "open downloads")
    assert w.state is OverlayState.HEARD
    assert "downloads" in w.preview
    assert w._lines  # transcript wrapped for paint
    assert w.isVisible()
    w.force(OverlayState.REST, "")
    assert not w.isVisible() or w._opacity == 0.0
    w.close()


def test_shoot_writes_four_lifecycle_pngs(qapp, tmp_path: Path) -> None:
    paths = shoot_overlay_states(tmp_path, app=qapp)
    names = sorted(p.name for p in paths)
    assert names == [
        "aurora-1-armed.png",
        "aurora-2-heard.png",
        "aurora-3-working.png",
        "aurora-4-speaking.png",
    ]
    for path in paths:
        assert path.is_file()
        assert path.stat().st_size > 1000  # not empty / stub
