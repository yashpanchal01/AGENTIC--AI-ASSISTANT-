"""Aurora Mono overlay — JARVIS lifecycle face (armed / heard / working / speaking).

Visual approach copied from LocalFlow's proven Aurora Mono pill (reference only;
LocalFlow itself is never modified): near-black glass, greyscale bars, state dot,
soft painted shadow, no focus steal.

States differ from LocalFlow (recording/processing) — JARVIS uses the PRD names:
armed → heard → working → speaking → rest.
"""

from __future__ import annotations

import math
import random
import time
from pathlib import Path

from jarvis.overlay.states import ACTIVE_STATES, STATE_TITLE, OverlayState

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError as exc:  # pragma: no cover - exercised when ui extra missing
    raise ImportError(
        "PySide6 is required for the overlay. Install with: "
        'py -3.13 -m pip install -e ".[ui]"'
    ) from exc


class _StateBridge(QtCore.QObject):
    """Carries (state, transcript|None, level|None) snapshots to the UI thread."""

    apply = QtCore.Signal(object)


def _ease_hard_s(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _wrap_tail(text: str, font: QtGui.QFont, avail: float, max_lines: int) -> list[str]:
    fm = QtGui.QFontMetrics(font)
    lines: list[str] = []
    line = ""
    for wd in (text or "").split():
        trial = (line + " " + wd).strip()
        if fm.horizontalAdvance(trial) > avail and line:
            lines.append(line)
            line = wd
        else:
            line = trial
    if line:
        lines.append(line)
    return lines[-max_lines:]


class AuroraOverlay(QtWidgets.QWidget):
    """Floating Aurora Mono pill. Never steals keyboard focus."""

    PILL_W = 344
    BASE_H = 46
    PAD = 26
    N_BARS = 12
    BG_TOP = QtGui.QColor(17, 17, 20, 247)
    BG_BOT = QtGui.QColor(8, 8, 10, 247)
    RIM_A = 42
    TEXT = QtGui.QColor(244, 244, 250)
    DIM = QtGui.QColor(140, 140, 162)
    PREV = QtGui.QColor(224, 224, 234)
    PREV_OLD = QtGui.QColor(150, 150, 160)

    # Greyscale bar gradients by state (Mono look).
    BARS: dict[OverlayState, tuple[QtGui.QColor, QtGui.QColor]] = {
        OverlayState.ARMED: (QtGui.QColor("#ececf2"), QtGui.QColor("#8d8d9c")),
        OverlayState.HEARD: (QtGui.QColor("#d8d8e4"), QtGui.QColor("#7a7a8c")),
        OverlayState.WORKING: (QtGui.QColor("#c9c9d4"), QtGui.QColor("#77778a")),
        OverlayState.SPEAKING: (QtGui.QColor("#e8e8f0"), QtGui.QColor("#9090a0")),
    }
    # Dot carries mode colour (quiet Mono chrome).
    DOT: dict[OverlayState, QtGui.QColor] = {
        OverlayState.ARMED: QtGui.QColor("#ff5c6a"),  # mic hot
        OverlayState.HEARD: QtGui.QColor("#5eb8ff"),  # transcript ready
        OverlayState.WORKING: QtGui.QColor("#ffb02e"),  # thinking
        OverlayState.SPEAKING: QtGui.QColor("#34d399"),  # reply playing
    }

    FADE_MS = 200
    EXPAND_MS = 320

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        flags = (
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowTransparentForInput
            | QtCore.Qt.WindowDoesNotAcceptFocus
        )
        super().__init__(parent, flags)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(QtCore.Qt.NoFocus)

        # Snapshot fields: applied on the UI thread; worker threads only emit.
        self.state: OverlayState = OverlayState.REST
        self.preview: str = ""
        self.level: float = 0.0

        self._shown_state: OverlayState = OverlayState.REST
        self._lvl = 0.0
        self._tick = 0
        self._heights = [3.0] * self.N_BARS
        self._phase = [random.uniform(0, 6.28) for _ in range(self.N_BARS)]
        self._speed = [random.uniform(0.35, 0.75) for _ in range(self.N_BARS)]
        self._lines: list[str] = []

        self._opacity = 0.0
        self._op_frm = self._op_to = 0.0
        self._op_t0 = 0.0
        self._h = float(self.BASE_H)
        self._h_frm = self._h_to = self._h
        self._h_t0 = 0.0
        self._paint_ph = float(self.BASE_H)

        self.f_title = QtGui.QFont("Segoe UI", 10, QtGui.QFont.DemiBold)
        self.f_prev = QtGui.QFont("Segoe UI", 9)

        # Marshal worker-thread set_state onto the UI thread (queued).
        self._bridge = _StateBridge(self)
        self._bridge.apply.connect(
            self._apply_snapshot, QtCore.Qt.QueuedConnection
        )

        self.setWindowOpacity(0.0)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.start(16)

    # -- Overlay protocol -----------------------------------------------------

    def set_state(
        self,
        state: OverlayState,
        *,
        transcript: str | None = None,
        level: float | None = None,
    ) -> None:
        """Update lifecycle state. Safe to call from the voice worker thread.

        Never calls Qt paint/show APIs here — only posts a snapshot for the UI
        thread (or applies inline when already on the UI thread).
        """
        snap = (state, transcript, level)
        if QtCore.QThread.currentThread() is self.thread():
            self._apply_snapshot(snap)
        else:
            self._bridge.apply.emit(snap)

    @QtCore.Slot(object)
    def _apply_snapshot(self, snap: object) -> None:
        state, transcript, level = snap  # type: ignore[misc]
        self.state = state
        if transcript is not None:
            self.preview = transcript
        if level is not None:
            self.level = level

    def close(self) -> None:  # noqa: A003 — matches Overlay protocol name
        self.timer.stop()
        super().close()

    # -- Harness helpers ------------------------------------------------------

    def force(self, state: OverlayState, preview: str = "", *, ticks: int = 70) -> None:
        """Settle animations for screenshot harness (no event loop needed)."""
        self.state = state
        self._shown_state = state
        self.preview = preview
        self._opacity = 1.0 if state in ACTIVE_STATES else 0.0
        self._op_frm = self._op_to = self._opacity
        for _ in range(ticks):
            self._tick += 1
            self.level = 0.55 if state is OverlayState.ARMED else 0.25
            self._lvl += (min(1.0, self.level) - self._lvl) * 0.35
            self._tick_bars()
            self._lines = _wrap_tail(self.preview, self.f_prev, self.PILL_W - 48, 2)
        self._h = float(self._pill_h())
        self._h_frm = self._h_to = self._h
        self._paint_ph = self._h
        self._place(self._h)
        self.setWindowOpacity(self._opacity)
        if state in ACTIVE_STATES:
            self.show()
        else:
            self.hide()

    # -- Animation ------------------------------------------------------------

    def _pill_h(self) -> int:
        return self.BASE_H + (len(self._lines) * 17 + 8 if self._lines else 0)

    def _place(self, ph: float | None = None) -> None:
        ph_i = self.BASE_H if ph is None else int(round(ph))
        win_w = self.PILL_W + self.PAD * 2
        win_h = ph_i + self.PAD * 2
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            self.setGeometry(100, 100, win_w, win_h)
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - win_w) // 2
        y = geo.y() + geo.height() - win_h - 30
        self.setGeometry(x, y, win_w, win_h)

    def _tick_bars(self) -> None:
        state = self._shown_state
        for i in range(self.N_BARS):
            if state is OverlayState.ARMED:
                wobble = 0.4 + 0.6 * abs(
                    math.sin(self._tick * self._speed[i] + self._phase[i])
                )
                target = 2.5 + 11.5 * wobble * (0.18 + 1.6 * self._lvl)
            elif state is OverlayState.SPEAKING:
                # Speech-like syllabic pulse.
                syll = abs(math.sin(self._tick * 0.28 + i * 0.4))
                target = 3 + 9.0 * syll
            elif state is OverlayState.WORKING:
                target = 3 + 6.5 * abs(math.sin(self._tick * 0.22 - i * 0.45))
            else:  # heard / rest
                target = 3 + 2.0 * abs(math.sin(self._tick * 0.08 + i * 0.3))
            target = min(target, 13.0)
            self._heights[i] += (target - self._heights[i]) * 0.45

    def _animate(self) -> None:
        now = time.perf_counter()
        self._tick += 1
        state = self.state
        active = state in ACTIVE_STATES

        if active and self._shown_state != state:
            self._shown_state = state

        target_op = 1.0 if active else 0.0
        if target_op != self._op_to:
            self._op_frm, self._op_to, self._op_t0 = self._opacity, target_op, now
        op_p = min(1.0, (now - self._op_t0) * 1000.0 / self.FADE_MS)
        self._opacity = self._op_frm + (self._op_to - self._op_frm) * _ease_hard_s(op_p)

        if not active and self._opacity < 0.04:
            if self.isVisible():
                self.hide()
                # Only clear transcript if we are still REST (worker may have
                # re-armed between fade start and this frame).
                if self.state not in ACTIVE_STATES:
                    self.preview = ""
                    self._lines = []
                self._h = self._h_frm = self._h_to = float(self.BASE_H)
            return

        if active and not self.isVisible():
            self._h = self._h_frm = self._h_to = float(self.BASE_H)
            self._place(self.BASE_H)
            self.show()
        self.setWindowOpacity(self._opacity)

        # Synthetic mic pulse when ARMED and no RMS was pushed (level stays 0).
        effective = self.level
        if state is OverlayState.ARMED and effective < 0.05:
            effective = 0.45 + 0.2 * abs(math.sin(self._tick * 0.15))
        self._lvl += (min(1.0, effective) - self._lvl) * 0.35
        self._tick_bars()
        self._lines = _wrap_tail(self.preview, self.f_prev, self.PILL_W - 48, 2)

        target_h = float(self._pill_h())
        if target_h != self._h_to:
            self._h_frm, self._h_to, self._h_t0 = self._h, target_h, now
        h_p = min(1.0, (now - self._h_t0) * 1000.0 / self.EXPAND_MS)
        self._h = self._h_frm + (self._h_to - self._h_frm) * _ease_hard_s(h_p)
        self._paint_ph = self._h

        win_w = self.PILL_W + self.PAD * 2
        win_h = int(round(self._h)) + self.PAD * 2
        if win_h != self.height() or win_w != self.width():
            self._place(self._h)
        self.update()

    # -- Paint ----------------------------------------------------------------

    def paintEvent(self, _ev: QtGui.QPaintEvent) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        ph = self._paint_ph
        px, py = self.PAD, self.PAD
        state = self._shown_state
        r = 20 if self._lines else ph / 2

        for grow, alpha in ((4, 30), (10, 15), (18, 6)):
            sp = QtGui.QPainterPath()
            sp.addRoundedRect(
                px - grow / 2,
                py - grow / 2 + 4,
                self.PILL_W + grow,
                ph + grow,
                r + grow / 2,
                r + grow / 2,
            )
            p.fillPath(sp, QtGui.QColor(0, 0, 0, alpha))

        body = QtGui.QPainterPath()
        body.addRoundedRect(px, py, self.PILL_W, ph, r, r)
        g = QtGui.QLinearGradient(0, py, 0, py + ph)
        g.setColorAt(0, self.BG_TOP)
        g.setColorAt(1, self.BG_BOT)
        p.fillPath(body, g)

        rim = QtGui.QLinearGradient(0, py, 0, py + ph)
        rim.setColorAt(0, QtGui.QColor(255, 255, 255, self.RIM_A))
        rim.setColorAt(0.35, QtGui.QColor(255, 255, 255, 12))
        rim.setColorAt(1, QtGui.QColor(255, 255, 255, 7))
        p.setPen(QtGui.QPen(QtGui.QBrush(rim), 1.2))
        p.drawPath(body)

        c1, c2 = self.BARS.get(state, (self.DIM, self.DIM))
        x0 = px + 22
        grad = QtGui.QLinearGradient(x0, 0, x0 + self.N_BARS * 6, 0)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        cy = py + self.BASE_H / 2
        for i in range(self.N_BARS):
            bh = self._heights[i]
            bx = x0 + i * 6
            bar = QtGui.QPainterPath()
            bar.addRoundedRect(bx, cy - bh, 3.0, bh * 2, 1.5, 1.5)
            p.fillPath(bar, QtGui.QBrush(grad))

        tx = x0 + self.N_BARS * 6 + 12
        dot = self.DOT.get(state)
        if dot is not None:
            dc = QtGui.QColor(dot)
            if state is OverlayState.ARMED and (self._tick // 16) % 2:
                dc.setAlpha(90)
            p.setBrush(dc)
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(QtCore.QPointF(tx + 3, cy), 3.4, 3.4)
            tx += 14

        p.setFont(self.f_title)
        p.setPen(self.TEXT)
        p.drawText(
            QtCore.QRectF(tx, py, 170, self.BASE_H),
            QtCore.Qt.AlignVCenter,
            STATE_TITLE.get(state, ""),
        )

        if self._lines:
            p.setFont(self.f_prev)
            for i, ln in enumerate(self._lines):
                older = i == 0 and len(self._lines) > 1
                col = QtGui.QColor(self.PREV_OLD if older else self.PREV)
                p.setPen(col)
                p.drawText(
                    QtCore.QPointF(x0, py + self.BASE_H + 4 + (i + 0.75) * 17),
                    ln,
                )
        p.end()


def compose_on_desktop(pm: QtGui.QPixmap, dpr: float) -> QtGui.QImage:
    """Place the grabbed pill on a fake desktop backdrop for visual review."""
    ov_w, ov_h = pm.width() / dpr, pm.height() / dpr
    cw, ch = max(820, int(ov_w) + 200), int(ov_h) + 170
    img = QtGui.QImage(
        int(cw * dpr),
        int(ch * dpr),
        QtGui.QImage.Format_ARGB32_Premultiplied,
    )
    img.setDevicePixelRatio(dpr)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)

    g = QtGui.QLinearGradient(0, 0, cw, ch)
    g.setColorAt(0, QtGui.QColor("#2b3050"))
    g.setColorAt(0.55, QtGui.QColor("#3c2e55"))
    g.setColorAt(1, QtGui.QColor("#1d2036"))
    p.fillRect(QtCore.QRectF(0, 0, cw, ch), g)

    win = QtCore.QRectF(cw * 0.12, 24, cw * 0.76, ch - 110)
    wp = QtGui.QPainterPath()
    wp.addRoundedRect(win, 8, 8)
    p.fillPath(wp, QtGui.QColor(248, 248, 250, 235))
    p.fillRect(
        QtCore.QRectF(win.x(), win.y(), win.width(), 26),
        QtGui.QColor(230, 230, 236),
    )
    p.setPen(QtGui.QColor(200, 202, 210))
    for i in range(5):
        y = win.y() + 48 + i * 16
        if y > win.bottom() - 14:
            break
        p.drawLine(
            QtCore.QPointF(win.x() + 20, y),
            QtCore.QPointF(win.right() - 20 - (i % 3) * 60, y),
        )
    p.fillRect(QtCore.QRectF(0, ch - 44, cw, 44), QtGui.QColor(10, 12, 20, 210))

    x, y = (cw - ov_w) / 2, ch - 44 - ov_h - 40
    p.drawPixmap(QtCore.QPointF(x, y), pm)
    p.end()
    return img


def shoot_overlay_states(
    out_dir: Path | str,
    *,
    app: QtWidgets.QApplication | None = None,
) -> list[Path]:
    """Render each lifecycle state to a PNG. Returns paths written."""
    own_app = False
    if app is None:
        existing = QtWidgets.QApplication.instance()
        if existing is None:
            app = QtWidgets.QApplication([])
            own_app = True
        else:
            app = existing  # type: ignore[assignment]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    screen = QtGui.QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0

    scenarios: list[tuple[str, OverlayState, str]] = [
        ("1-armed", OverlayState.ARMED, ""),
        (
            "2-heard",
            OverlayState.HEARD,
            "open my downloads folder and show the latest invoice",
        ),
        (
            "3-working",
            OverlayState.WORKING,
            "open my downloads folder and show the latest invoice",
        ),
        (
            "4-speaking",
            OverlayState.SPEAKING,
            "open my downloads folder and show the latest invoice",
        ),
    ]

    written: list[Path] = []
    for tag, state, preview in scenarios:
        w = AuroraOverlay()
        w.timer.stop()
        w.force(state, preview)
        pm = w.grab()
        img = compose_on_desktop(pm, dpr)
        path = out / f"aurora-{tag}.png"
        img.save(str(path))
        written.append(path)
        w.close()
        w.deleteLater()

    if own_app and app is not None:
        app.quit()
    return written


def run_overlay_demo(*, hold_s: float = 1.4) -> int:
    """Live cycle through armed → heard → working → speaking for visual QA."""
    import sys

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    overlay = AuroraOverlay()
    phases = [
        (OverlayState.ARMED, "", hold_s),
        (
            OverlayState.HEARD,
            "open notepad and maximise it",
            hold_s,
        ),
        (
            OverlayState.WORKING,
            "open notepad and maximise it",
            hold_s * 1.6,
        ),
        (
            OverlayState.SPEAKING,
            "open notepad and maximise it",
            hold_s,
        ),
        (OverlayState.REST, "", hold_s * 0.6),
    ]
    idx = {"i": 0}
    t0 = {"t": time.monotonic()}

    def tick() -> None:
        i = idx["i"]
        if i >= len(phases):
            overlay.close()
            app.quit()
            return
        state, preview, dur = phases[i]
        if time.monotonic() - t0["t"] > dur:
            idx["i"] = i + 1
            t0["t"] = time.monotonic()
            return
        overlay.set_state(state, transcript=preview, level=0.6 if state is OverlayState.ARMED else 0.2)
        if state is OverlayState.ARMED:
            overlay.level = 0.4 + 0.4 * abs(math.sin(time.monotonic() * 5))

    timer = QtCore.QTimer()
    timer.timeout.connect(tick)
    timer.start(33)
    # Kick first frame.
    overlay.set_state(OverlayState.ARMED, transcript="")
    return app.exec()
