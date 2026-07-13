"""MK.I SPINE overlay — event-bus port of the locked prototype (issue 18).

Ports the visual + animation machinery of ``jarvis_overlay_spine_locked.py``
(vertical MILSPEC notched plate, 5 states, the instrument pack + green success
pulse) onto the JARVIS event bus. The demo harness (keyboard state-cycling,
auto-cycle, scripted STEPS/WORDS/brain-cycling) is dropped — production is
event-driven.

Data model vs paint
-------------------
The surface state lives in :class:`jarvis.overlay.spine_surface.SpineSurface`
(no Qt, unit-testable). This widget only *renders* a snapshot of it and owns
the animation clocks. Events arrive on the bus/worker thread and are marshalled
onto the UI thread via Qt signals — Qt is never touched off the UI thread
(the Aurora pattern).

Selected via the ``overlay_style = "spine"`` setting; Aurora stays the default.
"""

from __future__ import annotations

import math
import os
import random
import socket
import threading
import time

from jarvis.overlay.spine_surface import (
    SpineSnapshot,
    SpineSurface,
    SpineSubscriber,
    SpineVisual,
)
from jarvis.overlay.states import OverlayState

try:
    from PySide6.QtCore import (
        QPointF,
        QRectF,
        Qt,
        QThread,
        QTimer,
        Signal,
    )
    from PySide6.QtCore import QObject as _QObject
    from PySide6.QtGui import (
        QColor,
        QFont,
        QFontMetricsF,
        QGuiApplication,
        QLinearGradient,
        QPainter,
        QPainterPath,
        QPen,
        QPolygonF,
    )
    from PySide6.QtWidgets import QApplication, QWidget
except ImportError as exc:  # pragma: no cover - exercised when ui extra missing
    raise ImportError(
        "PySide6 is required for the SPINE overlay. Install with: "
        'py -3.13 -m pip install -e ".[ui]"'
    ) from exc


# ---------------------------------------------------------------- palette
INK = (9, 10, 7)


def YEL(a: int = 255) -> QColor:
    return QColor(252, 238, 10, a)


def CYN(a: int = 255) -> QColor:
    return QColor(80, 235, 255, a)


def RD(a: int = 255) -> QColor:
    return QColor(255, 60, 70, a)


def AMB(a: int = 255) -> QColor:
    return QColor(255, 176, 32, a)


def WHT(a: int = 255) -> QColor:
    return QColor(232, 236, 226, a)


def GRY(a: int = 255) -> QColor:
    return QColor(150, 156, 142, a)


ACCENT: dict[SpineVisual, tuple[int, int, int]] = {
    SpineVisual.ARMED: (86, 178, 196),
    SpineVisual.HEARD: (80, 235, 255),
    SpineVisual.WORKING: (255, 108, 52),
    SpineVisual.SPEAKING: (252, 238, 10),
    SpineVisual.CONFIRM: (255, 176, 32),
    SpineVisual.FAULT: (255, 60, 70),
}
ENV_TARGET: dict[SpineVisual, float] = {
    SpineVisual.ARMED: 0.15,
    SpineVisual.HEARD: 1.0,
    SpineVisual.WORKING: 0.40,
    SpineVisual.SPEAKING: 0.92,
    SpineVisual.CONFIRM: 0.30,
    SpineVisual.FAULT: 0.10,
}
STATE_TEXT: dict[SpineVisual, str] = {
    SpineVisual.ARMED: "ARMED",
    SpineVisual.HEARD: "HEARD",
    SpineVisual.WORKING: "WORKING",
    SpineVisual.SPEAKING: "SPEAKING",
    SpineVisual.CONFIRM: "CONFIRM",
    SpineVisual.FAULT: "FAULT",
}
STATE_CODE: dict[SpineVisual, str] = {
    SpineVisual.ARMED: "STBY",
    SpineVisual.HEARD: "RECV",
    SpineVisual.WORKING: "EXEC",
    SpineVisual.SPEAKING: "XMIT",
    SpineVisual.CONFIRM: "HOLD",
    SpineVisual.FAULT: "FAIL",
}
MAIN_TAG: dict[SpineVisual, str] = {
    SpineVisual.ARMED: "SYS",
    SpineVisual.HEARD: "RX",
    SpineVisual.WORKING: "OP",
    SpineVisual.SPEAKING: "TX",
    SpineVisual.CONFIRM: "ASK",
    SpineVisual.FAULT: "ERR",
}
SUCCESS_RGB = (66, 235, 120)
SUCCESS_HOLD = 1.5
FAULT_FLASH_HOLD = 1.6
ARMED_HINT = 'standing by — say "jarvis"'
MUTED_HINT = "muted — not listening (resume to wake)"
SN = "SN.2077-113"
NC = "NC-077/YP"
GLYPHS = "!<>-_\\/[]{}=+*^?#$%&@01"


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def ease_out_cubic(u: float) -> float:
    u = clamp(u)
    return 1 - (1 - u) ** 3


def ease_out_back(u: float) -> float:
    u = clamp(u)
    c1 = 1.30
    c3 = c1 + 1
    u -= 1
    return 1 + c3 * u * u * u + c1 * u * u


_FONTS: dict[tuple, QFont] = {}


def F(fam, px, weight=QFont.Weight.Normal, spacing=None, stretch=None) -> QFont:
    key = (fam, px, int(weight), spacing, stretch)
    f = _FONTS.get(key)
    if f is None:
        f = QFont(fam)
        f.setPixelSize(px)
        f.setWeight(weight)
        if spacing:
            f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, spacing)
        if stretch:
            f.setStretch(stretch)
        _FONTS[key] = f
    return f


def MONO(px, weight=QFont.Weight.Normal, spacing=None) -> QFont:
    return F("Consolas", px, weight, spacing)


def COND(px, weight=QFont.Weight.DemiBold, spacing=112) -> QFont:
    return F("Bahnschrift", px, weight, spacing, stretch=82)


def elide(text, font, w) -> str:
    return QFontMetricsF(font).elidedText(text, Qt.ElideRight, w)


def tw(text, font) -> float:
    return QFontMetricsF(font).horizontalAdvance(text)


def _short_tool(name: str) -> str:
    """A 2-3 char badge from a dynamic step / tool name."""
    n = "".join(ch for ch in name.upper() if ch.isalnum())
    return n[:3] if n else "··"


def scanlines(p, path, step=4, alpha=5) -> None:
    br = path.boundingRect()
    p.save()
    p.setClipPath(path)
    p.setPen(QPen(QColor(255, 255, 255, alpha), 1))
    y = br.top() + 2
    while y < br.bottom():
        p.drawLine(QPointF(br.left(), y), QPointF(br.right(), y))
        y += step
    p.restore()


def hazard(p, x, y, w, h, color, spacing=11, width=5) -> None:
    p.save()
    p.setClipRect(QRectF(x, y, w, h))
    p.setPen(QPen(color, width))
    sx = x - h
    while sx < x + w:
        p.drawLine(QPointF(sx, y + h), QPointF(sx + h, y))
        sx += spacing
    p.restore()


def barcode(p, x, y, w, h, seed, alpha=90) -> None:
    rnd = random.Random(seed)
    p.setPen(Qt.NoPen)
    cx = x
    while cx < x + w:
        bw = rnd.choice((1, 1, 2, 3))
        if rnd.random() < 0.62:
            p.setBrush(WHT(alpha))
            p.drawRect(QRectF(cx, y, bw, h))
        cx += bw + rnd.choice((1, 2))


M = 30
PLATE_W = 300
PLATE_H = 488
PLATE_ALPHA = 132


class _EventBridge(_QObject):
    """Marshals worker-thread events onto the UI thread."""

    state_sig = Signal(object)  # (OverlayState, transcript|None, level|None)
    event_sig = Signal(object)  # a jarvis.events event


class SpineOverlay(QWidget):
    """Vertical MILSPEC SPINE plate. Implements the ``Overlay`` protocol and
    subscribes to the event bus for the rich instrument feed."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("JARVIS overlay — MK.I SPINE")

        self._surface = SpineSurface()
        self._snap: SpineSnapshot = self._surface.snapshot()

        # Marshal set_state / bus events onto the UI thread (never touch Qt off
        # the UI thread) — the Aurora pattern.
        self._bridge = _EventBridge(self)
        self._bridge.state_sig.connect(self._apply_state, Qt.QueuedConnection)
        self._bridge.event_sig.connect(self._apply_event, Qt.QueuedConnection)

        self._t0 = time.perf_counter()
        self.t = 0.0
        self._last_tick = 0.0

        # animation state
        self.env = 0.15
        self.acc_rgb = list(ACCENT[SpineVisual.ARMED])
        self.brain_act = 0.1
        self.glitch_t = -9.0
        self.success_t = -9.0
        self.fault_flash_t = -9.0
        self._seen_success = 0
        self._seen_faults = 0
        self.tok = 0.0
        self.tok_rate = 0.0
        self.spool_a = 0.0
        self.ctx_pct = 0.08
        self.shutter = 0.0
        self.vt = 0.0
        self._rate_ticks = 0
        self._rate_t = 0.0
        self._reveal = 0.0
        self._reveal_from = 0.0
        self._reveal_to = 0.0
        self._reveal_t0 = 0.0
        self._reveal_d = 0.001
        self._reveal_ease = ease_out_cubic
        self._drag = None

        # stats (real cpu/ram + connectivity; mock gpu random-walk like the proto)
        try:
            import psutil

            self._psutil = psutil
            psutil.cpu_percent(interval=None)
            self.cpu = 0.0
            self.ram = psutil.virtual_memory().percent
        except Exception:  # noqa: BLE001 — psutil optional; degrade gracefully
            self._psutil = None
            self.cpu = 0.0
            self.ram = 0.0
        self.gpu = 31.0
        self.gpu_tgt = 31.0
        self.online = False
        self._stop = False
        self._net_thread = threading.Thread(target=self._net_loop, daemon=True)
        self._net_thread.start()

        self._unsubscribers: list = []

        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(1000)
        self.stats_timer.timeout.connect(self._poll_stats)
        self.stats_timer.start()

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self._apply_geometry()

        if os.environ.get("JARVIS_SPINE_SMOKE") == "1":
            self._start_smoke()

    # -- Overlay protocol -----------------------------------------------------

    def set_state(
        self,
        state: OverlayState,
        *,
        transcript: str | None = None,
        level: float | None = None,
    ) -> None:
        """Lifecycle state from the pipeline. Safe from any thread."""
        snap = (state, transcript, level)
        if QThread.currentThread() is self.thread():
            self._apply_state(snap)
        else:
            self._bridge.state_sig.emit(snap)

    def close(self) -> None:  # noqa: A003 — matches Overlay protocol name
        self._stop = True
        for unsub in self._unsubscribers:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._unsubscribers = []
        try:
            self.timer.stop()
            self.stats_timer.stop()
        except Exception:  # noqa: BLE001
            pass
        super().close()

    # -- bus attach -----------------------------------------------------------

    def attach_events(self, bus) -> None:
        """Subscribe to the rich instrument events (StateChanged goes through
        the standard attach_overlay -> set_state path)."""
        subscriber = SpineSubscriber(_ForwardTo(self))
        self._unsubscribers.append(bus.subscribe(subscriber))

    def _dispatch_event(self, event: object) -> None:
        """Called by the bus subscriber (possibly off-thread) — marshal it."""
        if QThread.currentThread() is self.thread():
            self._apply_event(event)
        else:
            self._bridge.event_sig.emit(event)

    def _apply_state(self, snap) -> None:
        state, transcript, level = snap
        self._surface.apply_state(state, transcript=transcript, level=level)
        self._snap = self._surface.snapshot()

    def _apply_event(self, event: object) -> None:
        self._surface.handle_event(event)
        self._snap = self._surface.snapshot()

    # -- geometry / animation -------------------------------------------------

    def _now(self) -> float:
        return time.perf_counter() - self._t0

    def _apply_geometry(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.setGeometry(100, 100, PLATE_W, PLATE_H)
            return
        av = screen.availableGeometry()
        self.setGeometry(
            av.right() - PLATE_W - M, av.center().y() - PLATE_H // 2, PLATE_W, PLATE_H
        )

    def _reveal_target(self, target, dur, ease) -> None:
        self._reveal_from = self._reveal
        self._reveal_to = target
        self._reveal_t0 = self._now()
        self._reveal_d = max(dur, 0.001)
        self._reveal_ease = ease

    def reveal(self) -> float:
        u = (self._now() - self._reveal_t0) / self._reveal_d
        if u >= 1:
            return self._reveal_to
        return self._reveal_from + (self._reveal_to - self._reveal_from) * (
            self._reveal_ease(u)
        )

    def _visual(self) -> SpineVisual:
        snap = self._snap
        now = self._now()
        if now - self.fault_flash_t < FAULT_FLASH_HOLD:
            return SpineVisual.FAULT
        return snap.visual or SpineVisual.ARMED

    def _tick(self) -> None:
        now = self._now()
        dt = min(0.1, now - self._last_tick) if self._last_tick else 0.016
        self._last_tick = now
        self.t = now
        snap = self._snap

        # success pulse / fault glitch: detect surface counter changes
        if snap.success_pulses != self._seen_success:
            self._seen_success = snap.success_pulses
            self.success_t = now
        if snap.fault_events != self._seen_faults:
            self._seen_faults = snap.fault_events
            self.glitch_t = now
            self.fault_flash_t = now

        vis = self._visual()

        # mic privacy-shutter: closed (1.0) while not listening (resident
        # paused), open (0.0) while listening. Real state — not decorative.
        shutter_target = 1.0 if snap.mic_muted else 0.0
        self.shutter += (shutter_target - self.shutter) * 0.20

        # reveal: show while active, fade out at REST. Also reveal while muted so
        # the closed privacy-shutter is actually visible (the daemon otherwise
        # idles at REST with the plate hidden).
        want = 1.0 if (snap.active or snap.mic_muted) else 0.0
        if abs(want - self._reveal_to) > 0.001:
            self._reveal_target(
                want, 0.42 if want > 0 else 0.3, ease_out_back if want > 0 else ease_out_cubic
            )
        self._reveal = self.reveal()
        if snap.active and not self.isVisible() and self._reveal > 0.02:
            self.show()
            self.raise_()
        if not snap.active and self.isVisible() and self._reveal < 0.02:
            self.hide()

        self.vt += dt
        self.env += (ENV_TARGET.get(vis, 0.2) - self.env) * 0.075
        if now - self.success_t < SUCCESS_HOLD:
            tgt = SUCCESS_RGB
        else:
            tgt = ACCENT.get(vis, ACCENT[SpineVisual.ARMED])
        for k in range(3):
            self.acc_rgb[k] += (tgt[k] - self.acc_rgb[k]) * 0.10
        self.gpu += (self.gpu_tgt - self.gpu) * 0.02

        bt = 1.0 if vis is SpineVisual.WORKING else (
            0.08 if vis is SpineVisual.ARMED else 0.15
        )
        self.brain_act += (bt - self.brain_act) * 0.08

        # thought ticker: real token activity -> odometer + rate
        self.tok += (snap.token_chars - self.tok) * 0.20
        if now - self._rate_t >= 0.25:
            span = max(1e-3, now - self._rate_t)
            inst = (snap.token_ticks - self._rate_ticks) / span
            self.tok_rate += (inst - self.tok_rate) * 0.6
            self._rate_ticks = snap.token_ticks
            self._rate_t = now
        if vis not in (SpineVisual.WORKING, SpineVisual.SPEAKING):
            self.tok_rate *= 0.9
        self.spool_a += self.tok_rate * dt * 0.30
        self.ctx_pct = clamp(0.08 + self.tok / 30000.0, 0.0, 0.97)

        self.update()

    def _poll_stats(self) -> None:
        if self._psutil is not None:
            try:
                self.cpu = self._psutil.cpu_percent(interval=None)
                self.ram = self._psutil.virtual_memory().percent
            except Exception:  # noqa: BLE001
                pass
        if random.random() < 0.4:
            self.gpu_tgt = clamp(self.gpu_tgt + random.uniform(-14, 14), 6, 88)

    def _net_loop(self) -> None:
        while not self._stop:
            try:
                s = socket.create_connection(("1.1.1.1", 53), timeout=1.2)
                s.close()
                self.online = True
            except OSError:
                self.online = False
            for _ in range(50):
                if self._stop:
                    return
                time.sleep(0.1)

    # -- ctx accessors used by the painter ------------------------------------

    def acc(self, alpha: int = 255) -> QColor:
        r, g, b = self.acc_rgb
        return QColor(int(r), int(g), int(b), alpha)

    def _glitch(self) -> float:
        return max(0.0, 1.0 - (self.t - self.glitch_t) / 0.09)

    def up_str(self) -> str:
        mm, ss = divmod(int(self.t), 60)
        return f"{mm:02d}:{ss:02d}"

    def voice(self, i: int, n: int) -> float:
        x = i / max(1, n - 1)
        tt = self.vt
        v = abs(
            math.sin(tt * 2.9 + i * 0.83) * 0.55
            + math.sin(tt * 5.1 + i * 1.94) * 0.30
            + math.sin(tt * 8.7 + i * 3.1) * 0.15
        )
        bell = 0.35 + 0.65 * math.sin(math.pi * clamp(x))
        base = max(self.env, self._snap.level)
        return clamp(base * (0.15 + 0.85 * v) * bell, 0.04, 1.0)

    def brain_led(self, i: int) -> float:
        v = 0.5 + 0.5 * math.sin(self.t * 11.0 + i * 2.31)
        return clamp(self.brain_act * (0.25 + 0.95 * v))

    # -- paint ----------------------------------------------------------------

    def _silhouette(self, rr: QRectF) -> QPainterPath:
        x, y, w, h = rr.left(), rr.top(), rr.width(), rr.height()
        n0 = y + h * 0.26
        pts = [
            QPointF(x + 16, y), QPointF(x + w - 8, y), QPointF(x + w, y + 8),
            QPointF(x + w, y + h - 30), QPointF(x + w - 30, y + h),
            QPointF(x + 8, y + h), QPointF(x, y + h - 8),
            QPointF(x, n0 + 62), QPointF(x + 9, n0 + 54),
            QPointF(x + 9, n0 + 8), QPointF(x, n0),
            QPointF(x, y + 16),
        ]
        path = QPainterPath()
        path.addPolygon(QPolygonF(pts))
        path.closeSubpath()
        return path

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        a = self._reveal
        op = clamp(a)
        if op <= 0.004:
            p.end()
            return
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        s = 0.92 + 0.08 * a
        p.save()
        p.translate(cx, cy + (1 - min(a, 1.0)) * 14)
        p.scale(s, s)
        p.translate(-cx, -cy)
        p.setOpacity(op)
        self._paint_plate(p, QRectF(0, 0, w, h))
        p.restore()
        p.end()

    def _paint_plate(self, p: QPainter, r: QRectF) -> None:
        snap = self._snap
        vis = self._visual()
        rr = r.adjusted(5, 5, -5, -5)
        fault = vis is SpineVisual.FAULT

        g = self._glitch()
        if g > 0:
            rnd = random.Random(int(self.t * 90))
            p.save()
            p.translate(rnd.uniform(-4, 4) * g, rnd.uniform(-2, 2) * g)

        body = self._silhouette(rr)
        gr = QLinearGradient(rr.topLeft(), rr.bottomLeft())
        if fault:
            gr.setColorAt(0.0, QColor(48, 10, 12, PLATE_ALPHA + 20))
            gr.setColorAt(1.0, QColor(18, 4, 5, PLATE_ALPHA + 36))
        else:
            gr.setColorAt(0.0, QColor(14, 15, 11, PLATE_ALPHA))
            gr.setColorAt(1.0, QColor(INK[0], INK[1], INK[2], PLATE_ALPHA + 24))
        p.setPen(QPen(self.acc(210 if fault else 190), 1.5 if fault else 1.4))
        p.setBrush(gr)
        p.drawPath(body)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawPath(self._silhouette(rr.adjusted(3, 3, -3, -3)))
        scanlines(p, body, 4, 4)

        p.save()
        p.setClipPath(body)
        hazard(p, rr.left() + 8, rr.bottom() - 10, 96, 10, self.acc(150 if fault else 110))
        p.restore()

        x0 = rr.left() + 20
        x1 = rr.right() - 30
        y = rr.top()

        y = self._header(p, snap, vis, rr, x0, x1, y)
        y = self._state_banner(p, snap, vis, x0, x1, y)
        y = self._transcript(p, snap, vis, x0, x1, y)
        y = self._ledger(p, snap, vis, x0, x1, y)
        y = self._ticker(p, snap, vis, x0, x1, y)
        y = self._voice(p, snap, vis, x0, x1, y)

        # footer
        fy = rr.bottom() - 16
        p.setFont(MONO(7.5))
        p.setPen(GRY(140))
        p.drawText(QPointF(x0, fy), f"CTX {self.ctx_pct * 100:02.0f}% · UP {self.up_str()}")
        barcode(p, x1 - 54, fy - 7, 44, 7, SN, 60)
        p.setPen(GRY(100))
        p.drawText(QPointF(x1 - 54 - tw(NC, MONO(7.5)) - 8, fy), NC)

        # context gauge (left edge)
        gx = rr.left() + 5
        gy0, gy1 = rr.top() + 54, rr.bottom() - 18
        pct = self.ctx_pct
        if fault or pct >= 0.85:
            fill, tip, lab = RD(120), RD(230), RD(160)
        elif pct >= 0.65:
            fill, tip, lab = AMB(120), AMB(230), AMB(160)
        else:
            fill, tip, lab = self.acc(120), self.acc(230), GRY(120)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRect(QRectF(gx, gy0, 3, gy1 - gy0))
        fh = (gy1 - gy0) * pct
        p.setBrush(fill)
        p.drawRect(QRectF(gx, gy1 - fh, 3, fh))
        p.setBrush(tip)
        p.drawRect(QRectF(gx - 1, gy1 - fh - 2, 5, 2))
        p.setFont(MONO(6))
        p.setPen(lab)
        p.drawText(QPointF(gx - 2, gy0 - 4), "CTX")

        self._stat_rail(p, rr)

        if g > 0:
            p.setPen(Qt.NoPen)
            rnd = random.Random(int(self.t * 90) + 1)
            for _ in range(2):
                yy = rr.top() + rnd.uniform(8, rr.height() - 10)
                p.setBrush(RD(int(130 * g)))
                p.drawRect(QRectF(rr.left() + 4, yy, rr.width() - 8, 2))
            p.restore()

    def _header(self, p, snap, vis, rr, x0, x1, y) -> float:
        p.setFont(COND(15, QFont.Weight.ExtraBold, 120))
        p.setPen(YEL(235))
        p.drawText(QPointF(x0, y + 22), "J.A.R.V.I.S.")
        base = y + 22
        row2 = y + 38

        self._mic(p, x1 - 12, base - 10)

        fl = snap.fault_latched
        pl = 0.6 + 0.4 * math.sin(self.t * 2.2)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(RD(int(120 * pl)) if fl else QColor(255, 255, 255, 12))
        p.drawRect(QRectF(x1 - 36, base - 9, 7, 7))
        p.setFont(MONO(6))
        p.setPen(RD(170) if fl else GRY(90))
        p.drawText(QPointF(x1 - 37, base + 7), "FLT")

        working = vis is SpineVisual.WORKING
        pulse = 0.7 + 0.3 * math.sin(self.t * 8.0)
        p.setFont(MONO(8.5, QFont.Weight.Bold))
        p.setPen(YEL(int(150 + 105 * self.brain_act * pulse)))
        btxt = f"BRAIN//{snap.brain or '—'}"
        p.drawText(QPointF(x0, row2), btxt)
        p.setPen(Qt.NoPen)
        bx = x0 + tw(btxt, MONO(8.5, QFont.Weight.Bold)) + 8
        for i in range(4):
            lvl = self.brain_led(i)
            col = (self.acc if working else YEL)(25 + int(215 * lvl))
            p.setBrush(col)
            p.drawRect(QRectF(bx + i * 8, row2 - 7, 5, 7))
        p.setPen(QPen(YEL(90), 1))
        p.drawLine(QPointF(x0, row2 + 7), QPointF(x1, row2 + 7))
        return row2 + 12

    def _mic(self, p, cx, cy) -> None:
        p.setPen(QPen(WHT(190), 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(cx - 3, cy, 6, 9), 3, 3)
        p.drawArc(QRectF(cx - 6, cy + 3, 12, 10), 180 * 16, 180 * 16)
        p.drawLine(QPointF(cx, cy + 13), QPointF(cx, cy + 16))
        sh = self.shutter
        if sh > 0.01:
            area = QRectF(cx - 7, cy - 2, 14, 20)
            p.save()
            p.setClipRect(area)
            hh = area.height() * sh
            p.setPen(QPen(RD(200) if sh > 0.95 else AMB(180), 1))
            p.setBrush(QColor(20, 14, 12, 235))
            p.drawRect(QRectF(area.left(), area.top(), area.width(), hh))
            p.restore()

    def _state_banner(self, p, snap, vis, x0, x1, y) -> float:
        px = 15
        p.setFont(COND(px, QFont.Weight.ExtraBold, 124))
        p.setPen(self.acc(250))
        p.drawText(QPointF(x0, y + px + 4), STATE_TEXT.get(vis, ""))
        p.setFont(MONO(8, QFont.Weight.Bold))
        code = STATE_CODE.get(vis, "")
        p.setPen(self.acc(170))
        p.drawText(QPointF(x1 - tw(code, MONO(8, QFont.Weight.Bold)), y + px + 3), code)
        ly = y + px + 10
        p.setPen(QPen(self.acc(70), 1))
        p.drawLine(QPointF(x0, ly), QPointF(x1, ly))

        # commit ring: ConfirmRequested -> pulsing ring + banner until resolved
        if snap.commit_ring:
            ring_pl = 0.5 + 0.5 * math.sin(self.t * 4.0)
            rcx, rcy, rad = x1 - 8, y + px - 2, 7
            p.setPen(QPen(AMB(int(140 + 100 * ring_pl)), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(rcx, rcy), rad, rad)
            sweep = -int(360 * ((self.t * 0.6) % 1.0))
            p.setPen(QPen(AMB(235), 2))
            p.drawArc(QRectF(rcx - rad, rcy - rad, rad * 2, rad * 2), 90 * 16, sweep * 16)
        return ly + 8

    def _transcript(self, p, snap, vis, x0, x1, y) -> float:
        p.setFont(MONO(7.5, QFont.Weight.Bold, 112))
        p.setPen(self.acc(190))
        p.drawText(QPointF(x0, y + 9), MAIN_TAG.get(vis, "") + ":")
        p.setFont(MONO(9))
        if snap.commit_ring and snap.commit_prompt:
            txt = snap.commit_prompt
            p.setPen(AMB(220))
        elif vis is SpineVisual.FAULT and snap.fault_text:
            txt = snap.fault_text
            p.setPen(RD(220))
        elif snap.mic_muted:
            txt = MUTED_HINT
            p.setPen(AMB(200))
        elif vis is SpineVisual.ARMED and not snap.transcript:
            txt = ARMED_HINT
            p.setPen(GRY(150))
        else:
            txt = snap.transcript or "…"
            p.setPen(CYN(180) if vis is SpineVisual.WORKING else WHT(225))
        p.drawText(
            QRectF(x0 + 30, y, x1 - x0 - 30, 30),
            int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap),
            txt,
        )
        return y + 36

    def _ledger(self, p, snap, vis, x0, x1, y) -> float:
        rh = 20
        steps = snap.steps
        rows = max(len(steps), 1)
        for i, step in enumerate(steps):
            ry = y + i * rh + rh * 0.65
            gx = x0 + 2
            stt = step.status
            if stt == "active":
                pl = 0.6 + 0.4 * math.sin(self.t * 5.0)
                p.setFont(MONO(9, QFont.Weight.Bold))
                p.setPen(self.acc(int(255 * pl)))
                p.drawText(QPointF(gx - 2, ry), "◆")
            elif stt == "done":
                p.setFont(MONO(9))
                p.setPen(YEL(150))
                p.drawText(QPointF(gx - 2, ry), "✓")
            elif stt == "failed":
                p.setFont(MONO(10, QFont.Weight.Bold))
                p.setPen(RD(245))
                p.drawText(QPointF(gx - 3, ry), "✗")
            else:
                p.setFont(MONO(9))
                p.setPen(GRY(70))
                p.drawText(QPointF(gx - 1, ry), "·")

            tf = MONO(7.5)
            tcol, ttxt = GRY(120), ""
            if stt == "failed":
                ttxt, tcol = "ERR", RD(235)
            elif step.elapsed is not None:
                ttxt = f"{step.elapsed:.1f}s"
                tcol = AMB(220) if step.elapsed > 1.5 else GRY(150)
            elif stt == "active" and step.started_at:
                ttxt = f"{max(0.0, time.monotonic() - step.started_at):.1f}s"
                tcol = GRY(150)
            p.setFont(tf)
            p.setPen(tcol)
            timer_w = tw("T-0.0", tf) + 2
            if ttxt:
                p.drawText(QPointF(x1 - tw(ttxt, tf), ry), ttxt)

            # tool badge
            short = _short_tool(step.name)
            bf = MONO(6.5, QFont.Weight.Bold)
            bw = tw(short, bf) + 8
            bxr = x1 - timer_w - 6
            hot = stt == "active"
            p.setPen(QPen(self.acc(200) if hot else QColor(255, 255, 255, 45), 1))
            p.setBrush(self.acc(40) if hot else Qt.NoBrush)
            p.drawRect(QRectF(bxr - bw, ry - 8, bw, 10))
            p.setBrush(Qt.NoBrush)
            p.setFont(bf)
            p.setPen(self.acc(240) if hot else GRY(120))
            p.drawText(QPointF(bxr - bw + 4, ry), short)
            bw += 6

            avail = (x1 - timer_w - bw - 8) - (x0 + 14)
            label = step.label
            if stt == "active":
                p.setFont(MONO(8.5, QFont.Weight.Bold))
                p.setPen(WHT(238))
            elif stt == "failed":
                p.setFont(MONO(8.5, QFont.Weight.Bold))
                p.setPen(RD(220))
            else:
                p.setFont(MONO(8.5))
                p.setPen(GRY(120) if stt == "done" else GRY(80))
            p.drawText(QPointF(x0 + 14, ry), elide(label, MONO(8.5), avail))

        if not steps:
            p.setFont(MONO(8))
            p.setPen(GRY(80))
            p.drawText(QPointF(x0 + 2, y + rh * 0.65), "· no steps yet")

        by = y + rows * rh + 4
        return by + 12

    def _ticker(self, p, snap, vis, x0, x1, y) -> float:
        rate = self.tok_rate
        stalled = vis is SpineVisual.WORKING and rate < 2.0
        p.setFont(MONO(7, spacing=112))
        p.setPen(GRY(140))
        p.drawText(QPointF(x0, y + 8), "THOUGHT//")

        nd = 5
        ch, cw = 13, 9
        oy = y + 2
        f = MONO(9, QFont.Weight.Bold)
        fm = QFontMetricsF(f)
        for k in range(nd):
            cxk = x0 + 52 + (nd - 1 - k) * (cw + 2)
            cell = QRectF(cxk, oy, cw, ch)
            p.setPen(QPen(QColor(255, 255, 255, 36), 1))
            p.setBrush(QColor(INK[0], INK[1], INK[2], 200))
            p.drawRect(cell)
            p.setBrush(Qt.NoBrush)
            v = self.tok
            whole = int(v)
            frac = v - whole
            d = (whole // 10 ** k) % 10
            roll = frac if k == 0 else 0.0
            p.save()
            p.setClipRect(cell)
            p.setFont(f)
            p.setPen(YEL(225))
            baseY = cell.center().y() + fm.ascent() / 2 - 1
            p.drawText(
                QPointF(cxk + (cw - fm.horizontalAdvance(str(d))) / 2, baseY - roll * ch),
                str(d),
            )
            if roll > 0.001:
                d2 = (d + 1) % 10
                p.drawText(
                    QPointF(
                        cxk + (cw - fm.horizontalAdvance(str(d2))) / 2,
                        baseY + (1 - roll) * ch,
                    ),
                    str(d2),
                )
            p.restore()

        scx = x1 - 34
        scy = y + 7
        p.setPen(QPen(YEL(160), 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(scx, scy), 6, 6)
        for k in range(3):
            ang = self.spool_a + k * 2.094
            p.drawLine(
                QPointF(scx, scy),
                QPointF(scx + 5 * math.cos(ang), scy + 5 * math.sin(ang)),
            )
        p.setFont(MONO(7.5, QFont.Weight.Bold))
        if stalled:
            if (self.t * 2.5) % 1 < 0.6:
                p.setPen(AMB(235))
                p.drawText(QPointF(x1 - 24, y + 10), "STALL")
        else:
            p.setPen(GRY(160) if rate > 0.5 else GRY(90))
            p.drawText(QPointF(x1 - 24, y + 10), f"{rate:02.0f}T/S")
        return y + 28

    def _voice(self, p, snap, vis, x0, x1, y) -> float:
        vh = 20
        n = 30
        span = (x1 - x0) / n
        base = y + vh + 2
        p.setPen(Qt.NoPen)
        for i in range(n):
            lvl = self.voice(i, n)
            bh = 2 + lvl * vh
            p.setBrush(self.acc(40 + int(190 * lvl)))
            p.drawRect(QRectF(x0 + i * span, base - bh, span * 0.55, bh))
        return base + 8

    def _stat_rail(self, p, rr) -> None:
        rxc = rr.right() - 12
        ry = rr.top() + 64
        for lab, val in (("C", self.cpu), ("R", self.ram), ("G", self.gpu)):
            p.setPen(GRY(130))
            p.setFont(MONO(6))
            p.drawText(QPointF(rxc - 2, ry + 5), lab)
            filled = round(clamp(val / 100.0) * 4)
            for k in range(4):
                on = k < filled
                warn = on and val > 85 and k == filled - 1
                p.setPen(Qt.NoPen)
                p.setBrush(
                    RD(230) if warn else (YEL(190) if on else QColor(255, 255, 255, 20))
                )
                p.drawRect(QRectF(rxc - 3, ry + 24 - k * 5, 6, 3))
            ry += 36
        p.setPen(GRY(130))
        p.setFont(MONO(6))
        p.drawText(QPointF(rxc - 2, ry + 5), "N")
        for k in range(4):
            if self.online:
                p.setPen(Qt.NoPen)
                p.setBrush(CYN(150))
                p.drawRect(QRectF(rxc - 3, ry + 24 - k * 5, 6, 3))
            else:
                blink = (self.t * 2) % 1 < 0.5
                p.setPen(Qt.NoPen)
                p.setBrush(RD(200 if (k == 0 and blink) else 30))
                p.drawRect(QRectF(rxc - 3, ry + 24 - k * 5, 6, 3))

    # -- input (drag to move) -------------------------------------------------

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._drag is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _ev) -> None:  # noqa: N802
        self._drag = None

    def closeEvent(self, ev) -> None:  # noqa: N802
        self._stop = True
        super().closeEvent(ev)

    # -- smoke ----------------------------------------------------------------

    def _start_smoke(self) -> None:
        """Env-var GUI smoke: drive a fake event trace, then exit 0 (~2.5s)."""
        from jarvis.events import (
            BrainSelected,
            ConfirmRequested,
            ListeningChanged,
            StepFinished,
            StepStarted,
            TaskCompleted,
            TokenTick,
        )

        self._smoke_steps = [
            # Privacy-shutter closes while paused (not listening), then opens.
            lambda: self._apply_event(ListeningChanged(listening=False)),
            lambda: self._apply_event(ListeningChanged(listening=True)),
            lambda: self.set_state(OverlayState.ARMED, level=0.5),
            lambda: self.set_state(
                OverlayState.HEARD, transcript="play focus mix and log gpu temps"
            ),
            lambda: self._apply_event(BrainSelected(provider="claude")),
            lambda: self.set_state(OverlayState.WORKING),
            lambda: self._apply_event(
                StepStarted(name="spotify", detail="queue focus mix", step_id="s1")
            ),
            lambda: self._apply_event(TokenTick(text="queuing your focus mix ")),
            lambda: self._apply_event(
                StepFinished(name="spotify", detail="queue focus mix", step_id="s1")
            ),
            lambda: self._apply_event(
                StepStarted(name="Bash", detail="nvidia-smi", step_id="s2")
            ),
            lambda: self._apply_event(TokenTick(text="reading gpu temps ")),
            lambda: self._apply_event(
                ConfirmRequested(proposed_action="write gpu-log.md")
            ),
            lambda: self.set_state(OverlayState.CONFIRM, transcript="write gpu-log.md"),
            lambda: self.set_state(OverlayState.WORKING),
            lambda: self._apply_event(
                StepFinished(name="Bash", detail="nvidia-smi", step_id="s2")
            ),
            lambda: self.set_state(OverlayState.SPEAKING, transcript="done"),
            lambda: self._apply_event(
                TaskCompleted(reply="Focus mix playing. GPU logged.", ok=True)
            ),
        ]
        self._smoke_i = 0
        self._smoke_timer = QTimer(self)
        self._smoke_timer.setInterval(150)
        self._smoke_timer.timeout.connect(self._smoke_tick)
        self._smoke_timer.start()

    def _smoke_tick(self) -> None:
        if self._smoke_i < len(self._smoke_steps):
            try:
                self._smoke_steps[self._smoke_i]()
            except Exception as exc:  # noqa: BLE001
                print(f"SPINE SMOKE step error: {exc}", flush=True)
            self._smoke_i += 1
            return
        self._smoke_timer.stop()
        print("SMOKE OK: MK.I SPINE drove a full event trace clean", flush=True)
        app = QApplication.instance()
        if app is not None:
            app.quit()


class _ForwardTo:
    """Adapts SpineSubscriber (expects a surface) to marshal via the widget."""

    def __init__(self, overlay: SpineOverlay) -> None:
        self._overlay = overlay

    def handle_event(self, event: object) -> None:
        self._overlay._dispatch_event(event)


def run_spine_smoke() -> int:
    """Standalone GUI smoke entry: ``JARVIS_SPINE_SMOKE=1`` drives + exits 0."""
    import sys

    os.environ["JARVIS_SPINE_SMOKE"] = "1"
    app = QApplication.instance() or QApplication(sys.argv)
    ov = SpineOverlay()
    ov.set_state(OverlayState.ARMED, level=0.5)
    ov.show()
    ov.raise_()
    return app.exec()


__all__ = ["SpineOverlay", "run_spine_smoke"]
