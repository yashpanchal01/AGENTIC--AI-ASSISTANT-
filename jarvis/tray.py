"""System tray icon for the resident daemon (issue 11 / US-52).

Shows that JARVIS is alive; menu: Pause, Resume, Quit. Visual state
(icon colour + tooltip) distinguishes running vs paused.

All QSystemTrayIcon / QAction mutations run on the Qt UI thread via a
queued signal — pause/quit may be invoked from the daemon worker thread.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from jarvis.resident import ResidentController, ResidentState


def _make_icon_pixmap(color: str, size: int = 64):
    """Draw a simple circular status icon (no external asset files)."""
    from PySide6 import QtCore, QtGui

    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pix)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setBrush(QtGui.QColor(color))
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    margin = size // 8
    painter.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)
    # Small "J" mark for identity.
    painter.setPen(QtGui.QColor("#0a0a12"))
    font = QtGui.QFont("Segoe UI", max(10, size // 3), QtGui.QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pix.rect(), int(QtCore.Qt.AlignmentFlag.AlignCenter), "J")
    painter.end()
    return pix


def icon_for_state(state: str):
    """Return a QIcon for running / paused / stopping."""
    from PySide6 import QtGui

    # Running: aurora cyan; paused: amber; stopping: grey.
    colors = {
        "running": "#3de7ff",
        "paused": "#f0a030",
        "stopping": "#6a6a7a",
    }
    color = colors.get(state, colors["running"])
    return QtGui.QIcon(_make_icon_pixmap(color))


class JarvisTray:
    """Thin Qt glue around :class:`ResidentController`.

    Construct on the UI thread after a QApplication exists. Pause/resume/quit
    call into the controller; the controller remains the source of truth so
    unit tests can exercise the gate without Qt.
    """

    def __init__(
        self,
        controller: ResidentController,
        *,
        parent: Any = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        from PySide6 import QtCore, QtWidgets

        self.controller = controller
        self._on_quit = on_quit
        self._tray = QtWidgets.QSystemTrayIcon(parent)
        self._menu = QtWidgets.QMenu()

        self._act_pause = self._menu.addAction("Pause")
        self._act_resume = self._menu.addAction("Resume")
        self._menu.addSeparator()
        self._act_quit = self._menu.addAction("Quit")

        self._act_pause.triggered.connect(self._on_pause)
        self._act_resume.triggered.connect(self._on_resume)
        self._act_quit.triggered.connect(self._on_quit_clicked)

        self._tray.setContextMenu(self._menu)
        self._tray.setIcon(icon_for_state(controller.state))
        self._apply_visual(controller.state)
        self._tray.show()

        # UI-thread bridge: resident may notify from the daemon worker thread.
        class _StateBridge(QtCore.QObject):
            state_changed = QtCore.Signal(str)

        self._bridge = _StateBridge()
        self._bridge.state_changed.connect(
            self._apply_visual,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )

        prev = controller.on_state_change

        def _bridge_cb(state: ResidentState) -> None:
            if prev is not None:
                try:
                    prev(state)
                except Exception:
                    pass
            try:
                self._bridge.state_changed.emit(str(state))
            except Exception:
                pass

        controller.on_state_change = _bridge_cb

    @property
    def tray_icon(self) -> Any:
        return self._tray

    def _on_pause(self) -> None:
        self.controller.pause()

    def _on_resume(self) -> None:
        self.controller.resume()

    def _on_quit_clicked(self) -> None:
        self.controller.quit()
        if self._on_quit is not None:
            self._on_quit()

    def _apply_visual(self, state: str) -> None:
        """Must run on the Qt UI thread (queued from worker-thread notifications)."""
        self._tray.setIcon(icon_for_state(state))
        if state == "paused":
            tip = "JARVIS — paused (deaf)"
            self._act_pause.setEnabled(False)
            self._act_resume.setEnabled(True)
        elif state == "stopping":
            tip = "JARVIS — stopping…"
            self._act_pause.setEnabled(False)
            self._act_resume.setEnabled(False)
        else:
            tip = "JARVIS — running"
            self._act_pause.setEnabled(True)
            self._act_resume.setEnabled(False)
        self._tray.setToolTip(tip)

    def hide(self) -> None:
        self._tray.hide()
