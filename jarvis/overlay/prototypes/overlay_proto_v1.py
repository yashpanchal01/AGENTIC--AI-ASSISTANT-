# =============================================================================
#  PROTOTYPE — THROWAWAY. JARVIS overlay design explorer. Not production code.
#
#  Question it answers: what should the JARVIS desktop overlay look/move like?
#  7 radically different live variants, real window, real animations.
#
#  Run:    py -3.13 jarvis_overlay_proto.py
#  Keys:   Left/Right = switch variant   Space = advance state
#          A = toggle auto-cycle of states   Esc = quit
#  Drag anywhere with the mouse to move the overlay.
#
#  Smoke test hook (dev only): JARVIS_PROTO_SMOKE=1 -> auto-cycles every
#  variant + state, then exits by itself. Normal runs are unaffected.
# =============================================================================

import math
import os
import random
import socket
import sys
import threading
import time

import psutil
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
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
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

SMOKE = os.environ.get("JARVIS_PROTO_SMOKE") == "1"

# ---------------------------------------------------------------- state model
STATES = ["ARMED", "HEARD", "WORKING", "SPEAKING"]
ACCENT = {
    "ARMED": (86, 208, 255),      # cyan
    "HEARD": (255, 195, 92),      # amber
    "WORKING": (186, 142, 255),   # violet
    "SPEAKING": (96, 234, 158),   # green
}
ENV_TARGET = {"ARMED": 0.16, "HEARD": 1.0, "WORKING": 0.45, "SPEAKING": 0.92}
MAIN_LABEL = {"ARMED": "WAKE", "HEARD": "YOU", "WORKING": "TASK", "SPEAKING": "JARVIS"}

WORDS = 'jarvis open notepad and check the gpu temperature'.split()
STEPS = ["parsing intent…", "opening notepad…", "reading gpu sensors…", "composing reply…"]
REPLY = "Notepad is open. GPU at 43°C — all systems nominal."
ARMED_HINT = 'standing by — say "jarvis"'

# ------------------------------------------------------------------- helpers
GLYPHS = "!<>-_\\/[]{}=+*^?#$%&@01"


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def ease_out_cubic(u):
    u = clamp(u)
    return 1 - (1 - u) ** 3


def ease_in_cubic(u):
    u = clamp(u)
    return u * u * u


def ease_out_back(u):
    u = clamp(u)
    c1 = 1.30
    c3 = c1 + 1
    u -= 1
    return 1 + c3 * u * u * u + c1 * u * u


_FONTS = {}


def F(fam, px, weight=QFont.Weight.Normal, spacing=None):
    key = (fam, px, int(weight), spacing)
    f = _FONTS.get(key)
    if f is None:
        f = QFont(fam)
        f.setPixelSize(px)
        f.setWeight(weight)
        if spacing:
            f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, spacing)
        _FONTS[key] = f
    return f


def MONO(px, weight=QFont.Weight.Normal, spacing=None):
    return F("Consolas", px, weight, spacing)


def SANS(px, weight=QFont.Weight.Normal, spacing=None):
    return F("Segoe UI", px, weight, spacing)


def rrect(r, rad):
    path = QPainterPath()
    path.addRoundedRect(r, rad, rad)
    return path


def glass(p, r, rad=16, alpha=232, stroke=36):
    """Dark frosted panel with a thin light stroke + top highlight."""
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0.0, QColor(20, 25, 34, alpha - 18))
    g.setColorAt(1.0, QColor(8, 10, 15, alpha))
    p.setPen(QPen(QColor(255, 255, 255, stroke), 1))
    p.setBrush(g)
    p.drawRoundedRect(r, rad, rad)
    p.setPen(QPen(QColor(255, 255, 255, 14), 1))
    p.drawLine(QPointF(r.left() + rad, r.top() + 1), QPointF(r.right() - rad, r.top() + 1))
    p.setBrush(Qt.NoBrush)


class Scramble:
    """Text decode effect: characters resolve left-to-right with jitter."""

    def __init__(self):
        self.target = ""
        self.resolve = []  # absolute resolve time per char

    def set(self, text, now, keep_prefix=True):
        pre = 0
        if keep_prefix:
            m = min(len(self.target), len(text))
            while pre < m and self.target[pre] == text[pre]:
                pre += 1
        self.resolve = self.resolve[:pre]
        for i in range(pre, len(text)):
            self.resolve.append(now + 0.035 * (i - pre) + random.random() * 0.22)
        self.target = text

    def text(self, now):
        out = []
        for ch, rt in zip(self.target, self.resolve):
            if ch == " " or now >= rt:
                out.append(ch)
            else:
                out.append(random.choice(GLYPHS))
        return "".join(out)


# ================================================================== variants
# Each variant: NAME, TAG (one-line personality), geometry(avail)->QRect,
# paint(p, ctx, r). ctx is the Overlay (state, accents, stats, voice, text).

M = 26  # screen margin


class VSlate:
    NAME = "SLATE"
    TAG = "frosted status card — calm, professional"

    def geometry(self, av):
        w, h = 396, 216
        return QRect(av.right() - w - M, av.top() + M, w, h)

    def paint(self, p, ctx, r):
        rr = r.adjusted(4, 4, -4, -4)
        glass(p, rr, 18)
        acc = ctx.acc

        # accent spine, breathing
        sp = QRectF(rr.left() + 1.5, rr.top() + 20, 3, rr.height() - 40)
        p.setPen(Qt.NoPen)
        p.setBrush(acc(150 + int(70 * math.sin(ctx.t * 2.0) ** 2)))
        p.drawRoundedRect(sp, 1.5, 1.5)

        # header: pulsing dot + state
        cx, cy = rr.left() + 26, rr.top() + 26
        pl = 0.5 + 0.5 * math.sin(ctx.t * 2.4)
        g = QRadialGradient(QPointF(cx, cy), 11)
        g.setColorAt(0, acc(int(90 + 90 * pl)))
        g.setColorAt(1, acc(0))
        p.setBrush(g)
        p.drawEllipse(QPointF(cx, cy), 11, 11)
        p.setBrush(acc(255))
        p.drawEllipse(QPointF(cx, cy), 3.4, 3.4)

        p.setFont(SANS(13, QFont.Weight.DemiBold, 128))
        p.setPen(QColor(240, 245, 250, 240))
        p.drawText(QPointF(cx + 14, cy + 5), ctx.state_text())

        # online chip, right
        p.setFont(MONO(10))
        net = "ONLINE" if ctx.online else "OFFLINE"
        nc = QColor(105, 240, 174, 210) if ctx.online else QColor(255, 110, 110, 220)
        fm = QFontMetricsF(MONO(10))
        nw = fm.horizontalAdvance(net)
        p.setPen(nc)
        p.drawText(QPointF(rr.right() - 18 - nw, cy + 4), net)
        p.setBrush(nc)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(rr.right() - 26 - nw, cy), 2.6, 2.6)

        # main label + text
        p.setFont(MONO(10, spacing=115))
        p.setPen(acc(190))
        p.drawText(QPointF(rr.left() + 26, rr.top() + 62), MAIN_LABEL[ctx.state()])
        p.setFont(SANS(15))
        p.setPen(QColor(235, 240, 246, 235))
        box = QRectF(rr.left() + 26, rr.top() + 70, rr.width() - 52, 58)
        p.drawText(box, int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap), ctx.main_text())

        # divider
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        y = rr.bottom() - 52
        p.drawLine(QPointF(rr.left() + 22, y), QPointF(rr.right() - 22, y))

        # voice bars, bottom-left
        n = 26
        bx, bw, gap = rr.left() + 26, 4.0, 3.0
        base = rr.bottom() - 24
        p.setPen(Qt.NoPen)
        for i in range(n):
            lvl = ctx.voice(i, n)
            bh = 3 + lvl * 24
            p.setBrush(acc(70 + int(170 * lvl)))
            p.drawRoundedRect(QRectF(bx + i * (bw + gap), base - bh, bw, bh), 2, 2)

        # stats, bottom-right
        p.setFont(MONO(10))
        p.setPen(QColor(200, 210, 222, 150))
        s = f"CPU {ctx.cpu:>3.0f}  RAM {ctx.ram:>3.0f}  GPU {ctx.gpu:>3.0f}"
        sw = QFontMetricsF(MONO(10)).horizontalAdvance(s)
        p.drawText(QPointF(rr.right() - 22 - sw, rr.bottom() - 20), s)


class VReactor:
    NAME = "REACTOR"
    TAG = "arc-reactor core — showy, Stark-lab energy"

    def geometry(self, av):
        w, h = 352, 356
        return QRect(av.right() - w - M, av.center().y() - h // 2, w, h)

    def paint(self, p, ctx, r):
        acc = ctx.acc
        c = QPointF(r.center().x(), r.center().y() - 14)
        R = 118.0

        # dark disc backdrop
        g = QRadialGradient(c, R + 46)
        g.setColorAt(0.0, QColor(8, 11, 17, 235))
        g.setColorAt(0.82, QColor(8, 11, 17, 205))
        g.setColorAt(1.0, QColor(8, 11, 17, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, R + 46, R + 46)

        # outer thin ring
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawEllipse(c, R, R)

        # radial voice equalizer (inward ticks)
        n = 56
        for i in range(n):
            lvl = ctx.voice(i, n)
            a = (i / n) * 2 * math.pi - math.pi / 2
            ca, sa = math.cos(a), math.sin(a)
            r1, r0 = R - 5, R - 5 - lvl * 22
            p.setPen(QPen(acc(50 + int(180 * lvl)), 2))
            p.drawLine(QPointF(c.x() + ca * r0, c.y() + sa * r0),
                       QPointF(c.x() + ca * r1, c.y() + sa * r1))

        # rotating arcs
        arc = QRectF(c.x() - R + 16, c.y() - R + 16, 2 * (R - 16), 2 * (R - 16))
        p.setPen(QPen(acc(210), 2.4, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(arc, int((ctx.t * 52 % 360) * 16), 76 * 16)
        arc2 = arc.adjusted(9, 9, -9, -9)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1.4, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(arc2, int((-ctx.t * 34 % 360) * 16), 118 * 16)

        # core glow + kernel
        k = 1.0 + 0.10 * ctx.env * math.sin(ctx.t * 8.0) + 0.04 * math.sin(ctx.t * 1.9)
        g = QRadialGradient(c, 52 * k)
        g.setColorAt(0.0, acc(200))
        g.setColorAt(0.45, acc(70))
        g.setColorAt(1.0, acc(0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, 52 * k, 52 * k)
        g = QRadialGradient(QPointF(c.x() - 3, c.y() - 4), 15 * k)
        g.setColorAt(0.0, QColor(255, 255, 255, 235))
        g.setColorAt(1.0, acc(160))
        p.setBrush(g)
        p.drawEllipse(c, 13 * k, 13 * k)

        # state under core
        p.setFont(SANS(13, QFont.Weight.DemiBold, 160))
        p.setPen(QColor(242, 246, 252, 245))
        p.drawText(QRectF(r.left(), c.y() + 26, r.width(), 22), int(Qt.AlignHCenter), ctx.state_text())

        # main text
        p.setFont(MONO(10))
        p.setPen(QColor(225, 232, 240, 200))
        p.drawText(QRectF(r.left() + 62, c.y() + 50, r.width() - 124, 44),
                   int(Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap), ctx.main_text())

        # stats row at bottom
        p.setFont(MONO(9))
        p.setPen(QColor(190, 200, 214, 150))
        net = "NET▲" if ctx.online else "NET▽"
        s = f"CPU {ctx.cpu:>3.0f} · RAM {ctx.ram:>3.0f} · GPU {ctx.gpu:>3.0f} · {net}"
        p.drawText(QRectF(r.left(), r.bottom() - 26, r.width(), 16), int(Qt.AlignHCenter), s)


class VTicker:
    NAME = "TICKER"
    TAG = "full-width bottom strip — ambient, stays out of the way"

    def geometry(self, av):
        w = min(1120, av.width() - 200)
        h = 62
        return QRect(av.center().x() - w // 2, av.bottom() - h - 18, w, h)

    def paint(self, p, ctx, r):
        acc = ctx.acc
        bar = r.adjusted(4, 6, -4, -6)
        glass(p, bar, 14)
        p.save()
        p.setClipPath(rrect(bar, 14))

        # left state chip
        chip = QRectF(bar.left(), bar.top(), 148, bar.height())
        g = QLinearGradient(chip.topLeft(), chip.topRight())
        g.setColorAt(0, acc(52))
        g.setColorAt(1, acc(8))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRect(chip)
        p.setPen(QPen(acc(170), 1))
        p.drawLine(QPointF(chip.right(), chip.top()), QPointF(chip.right(), chip.bottom()))
        pl = 0.5 + 0.5 * math.sin(ctx.t * 2.6)
        p.setPen(Qt.NoPen)
        p.setBrush(acc(140 + int(115 * pl)))
        p.drawEllipse(QPointF(chip.left() + 20, chip.center().y()), 3.2, 3.2)
        p.setFont(SANS(12, QFont.Weight.DemiBold, 130))
        p.setPen(acc(245))
        p.drawText(QRectF(chip.left() + 32, chip.top(), chip.width() - 36, chip.height()),
                   int(Qt.AlignVCenter | Qt.AlignLeft), ctx.state_text())

        # center: label + single-line text (elided)
        p.setFont(MONO(10))
        p.setPen(QColor(160, 172, 186, 170))
        lab = f"[{MAIN_LABEL[ctx.state()]}]"
        lx = chip.right() + 18
        p.drawText(QPointF(lx, bar.center().y() + 4), lab)
        lw = QFontMetricsF(MONO(10)).horizontalAdvance(lab)
        tx = lx + lw + 10
        wave_w = 150.0
        stats_w = 216.0
        avail_w = bar.right() - stats_w - wave_w - 30 - tx
        p.setFont(MONO(12))
        fm = QFontMetricsF(MONO(12))
        txt = fm.elidedText(ctx.main_text(), Qt.ElideRight, avail_w)
        p.setPen(QColor(235, 240, 246, 235))
        p.drawText(QPointF(tx, bar.center().y() + 4.5), txt)

        # waveform segment
        wx0 = bar.right() - stats_w - wave_w - 12
        mid = bar.center().y()
        pts = []
        for i in range(64):
            x = i / 63.0
            pts.append(QPointF(wx0 + x * wave_w, mid + ctx.wave(x) * 16))
        p.setPen(QPen(acc(200), 1.6))
        p.drawPolyline(QPolygonF(pts))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawLine(QPointF(wx0, mid), QPointF(wx0 + wave_w, mid))

        # right stats
        p.setFont(MONO(10))
        p.setPen(QColor(200, 210, 222, 160))
        s = f"CPU {ctx.cpu:>3.0f}  RAM {ctx.ram:>3.0f}  GPU {ctx.gpu:>3.0f}"
        p.drawText(QPointF(bar.right() - stats_w + 14, mid + 4), s)
        nc = QColor(105, 240, 174, 220) if ctx.online else QColor(255, 110, 110, 230)
        p.setPen(Qt.NoPen)
        p.setBrush(nc)
        p.drawEllipse(QPointF(bar.right() - 16, mid), 3.0, 3.0)
        p.restore()


class VGhost:
    NAME = "GHOST"
    TAG = "bare terminal text — hacker/CLI attitude"

    def geometry(self, av):
        w, h = 474, 212
        return QRect(av.left() + M, av.bottom() - h - M - 6, w, h)

    def paint(self, p, ctx, r):
        acc = ctx.acc
        rr = r.adjusted(4, 4, -4, -4)

        # ultra-faint backdrop + scanlines
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(4, 8, 10, 158))
        p.drawRoundedRect(rr, 6, 6)
        p.save()
        p.setClipPath(rrect(rr, 6))
        p.setPen(QPen(QColor(255, 255, 255, 6), 1))
        y = rr.top() + 3
        while y < rr.bottom():
            p.drawLine(QPointF(rr.left(), y), QPointF(rr.right(), y))
            y += 4
        p.restore()
        p.setPen(QPen(acc(60), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rr, 6, 6)

        x = rr.left() + 16
        mono = MONO(11)
        fm = QFontMetricsF(mono)
        lh = fm.height() + 3
        yy = rr.top() + 10 + fm.ascent()

        mm, ss = divmod(int(ctx.t), 60)
        p.setFont(mono)
        p.setPen(QColor(140, 155, 168, 160))
        p.drawText(QPointF(x, yy), f"┌─ JARVIS/proto ── uptime {mm:02d}:{ss:02d} " + "─" * 14)
        yy += lh

        p.setPen(QColor(140, 155, 168, 190))
        p.drawText(QPointF(x, yy), "state:")
        p.setFont(MONO(11, QFont.Weight.Bold))
        p.setPen(acc(240))
        p.drawText(QPointF(x + fm.horizontalAdvance("state: "), yy), ctx.state_text())
        yy += lh

        blink = "▌" if (ctx.t * 2.2) % 1 < 0.55 else " "
        p.setFont(mono)
        p.setPen(QColor(222, 236, 228, 225))
        box = QRectF(x, yy - fm.ascent(), rr.width() - 32, lh * 2.1)
        p.drawText(box, int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap),
                   "$ " + ctx.main_text() + blink)
        yy += lh * 2.15

        # ascii-style voice meter (drawn as mini rects)
        n = 44
        bx, bw = x, 6.0
        base = yy + 2
        p.setPen(Qt.NoPen)
        for i in range(n):
            lvl = ctx.voice(i, n)
            bh = 1.5 + lvl * 13
            p.setBrush(acc(55 + int(180 * lvl)))
            p.drawRect(QRectF(bx + i * (bw + 2.4), base - bh, bw, bh))
        yy += lh + 4

        p.setFont(MONO(10))
        p.setPen(QColor(150, 165, 178, 170))
        net = "net:up" if ctx.online else "net:DOWN"
        p.drawText(QPointF(x, yy + 4),
                   f"[cpu {ctx.cpu:>3.0f}%] [ram {ctx.ram:>3.0f}%] [gpu {ctx.gpu:>3.0f}%] [{net}]")


class VBastion:
    NAME = "BASTION"
    TAG = "hexagonal plate — angular military HUD"

    def geometry(self, av):
        w, h = 356, 316
        return QRect(av.left() + M, av.top() + M, w, h)

    def paint(self, p, ctx, r):
        acc = ctx.acc
        c = QPointF(r.center().x(), r.center().y())
        R = 138.0

        def hexpts(rad, rot=0.0):
            pts = []
            for k in range(6):
                a = math.radians(60 * k - 90 + rot)
                pts.append(QPointF(c.x() + rad * math.cos(a), c.y() + rad * math.sin(a)))
            return QPolygonF(pts)

        # plate
        path = QPainterPath()
        path.addPolygon(hexpts(R))
        path.closeSubpath()
        g = QLinearGradient(QPointF(c.x(), c.y() - R), QPointF(c.x(), c.y() + R))
        g.setColorAt(0, QColor(16, 21, 29, 224))
        g.setColorAt(1, QColor(7, 9, 14, 238))
        p.setPen(QPen(QColor(255, 255, 255, 46), 1.2))
        p.setBrush(g)
        p.drawPath(path)
        p.setPen(QPen(acc(46), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(hexpts(R - 7))

        # corner brackets at window corners
        p.setPen(QPen(QColor(255, 255, 255, 70), 1.4))
        L = 13
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            px = r.left() + 8 if sx > 0 else r.right() - 8
            py = r.top() + 8 if sy > 0 else r.bottom() - 8
            p.drawLine(QPointF(px, py), QPointF(px + sx * L, py))
            p.drawLine(QPointF(px, py), QPointF(px, py + sy * L))

        # segmented state ring: 4 segments, current lit
        ring = QRectF(c.x() - (R - 26), c.y() - (R - 26), 2 * (R - 26), 2 * (R - 26))
        rot = ctx.t * 7.0
        for k in range(4):
            lit = k == ctx.state_i
            p.setPen(QPen(acc(220) if lit else QColor(255, 255, 255, 30),
                          3.0 if lit else 1.6, Qt.SolidLine, Qt.FlatCap))
            p.drawArc(ring, int((90 - k * 90 + 10 + rot) * 16), 70 * 16)

        # center text
        p.setFont(SANS(14, QFont.Weight.DemiBold, 150))
        p.setPen(QColor(242, 246, 252, 245))
        p.drawText(QRectF(r.left(), c.y() - 58, r.width(), 24), int(Qt.AlignHCenter), ctx.state_text())
        p.setFont(MONO(10))
        p.setPen(QColor(222, 230, 240, 205))
        p.drawText(QRectF(c.x() - 92, c.y() - 30, 184, 48),
                   int(Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap), ctx.main_text())

        # LED voice meter
        cells = 16
        lit_n = round(sum(ctx.voice(i, cells) for i in range(cells)) / cells * cells * 1.35)
        cw, ch, gap = 8.0, 11.0, 3.0
        total = cells * cw + (cells - 1) * gap
        bx = c.x() - total / 2
        by = c.y() + 30
        p.setPen(Qt.NoPen)
        for i in range(cells):
            on = i < lit_n
            p.setBrush(acc(225) if on else QColor(255, 255, 255, 20))
            p.drawRect(QRectF(bx + i * (cw + gap), by, cw, ch))

        # stats
        p.setFont(MONO(9))
        p.setPen(QColor(185, 196, 210, 155))
        net = "NET+" if ctx.online else "NET-"
        p.drawText(QRectF(r.left(), c.y() + 56, r.width(), 16), int(Qt.AlignHCenter),
                   f"CPU{ctx.cpu:>3.0f} RAM{ctx.ram:>3.0f} GPU{ctx.gpu:>3.0f} {net}")


class VCompanion:
    NAME = "COMPANION"
    TAG = "breathing orb + speech pill — friendly, approachable"

    def geometry(self, av):
        w, h = 476, 172
        return QRect(av.right() - w - M, av.bottom() - h - M - 6, w, h)

    def paint(self, p, ctx, r):
        acc = ctx.acc
        oc = QPointF(r.left() + 72, r.center().y())
        R = 34 * (1 + 0.05 * math.sin(ctx.t * 1.8) + 0.09 * ctx.env * math.sin(ctx.t * 9.3))

        # ripples while active
        if ctx.env > 0.22:
            for k in range(3):
                ph = (ctx.t * 0.55 + k / 3.0) % 1.0
                alpha = int((1 - ph) * 80 * ctx.env)
                if alpha > 3:
                    p.setPen(QPen(acc(alpha), 1.6))
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(oc, R + 6 + ph * 36, R + 6 + ph * 36)

        # orb
        g = QRadialGradient(QPointF(oc.x() - R * 0.3, oc.y() - R * 0.35), R * 1.9)
        g.setColorAt(0.0, acc(250))
        g.setColorAt(0.55, acc(120))
        g.setColorAt(1.0, QColor(8, 10, 15, 235))
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(g)
        p.drawEllipse(oc, R, R)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 170))
        p.drawEllipse(QPointF(oc.x() - R * 0.35, oc.y() - R * 0.42), 4.5, 3.2)

        # online ring
        pen = QPen(acc(120) if ctx.online else QColor(255, 110, 110, 150), 1.2)
        if not ctx.online:
            pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(oc, R + 7, R + 7)

        # small equalizer arc, right side of orb
        for i in range(10):
            lvl = ctx.voice(i, 10)
            a = math.radians(-58 + i * 13)
            ca, sa = math.cos(a), math.sin(a)
            r0, r1 = R + 12, R + 12 + lvl * 15
            p.setPen(QPen(acc(60 + int(170 * lvl)), 2))
            p.drawLine(QPointF(oc.x() + ca * r0, oc.y() + sa * r0),
                       QPointF(oc.x() + ca * r1, oc.y() + sa * r1))

        # speech pill
        pill = QRectF(r.left() + 138, r.center().y() - 52, r.width() - 152, 104)
        glass(p, pill, 26)
        p.setFont(SANS(10, QFont.Weight.DemiBold, 140))
        p.setPen(acc(220))
        p.drawText(QPointF(pill.left() + 24, pill.top() + 26),
                   f"{ctx.state_text()} · {MAIN_LABEL[ctx.state()]}")
        p.setFont(SANS(13))
        p.setPen(QColor(236, 241, 247, 235))
        p.drawText(QRectF(pill.left() + 24, pill.top() + 34, pill.width() - 48, 52),
                   int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap), ctx.main_text())

        # micro stats under pill
        p.setFont(MONO(9))
        p.setPen(QColor(185, 196, 210, 150))
        net = "net ok" if ctx.online else "net down"
        p.drawText(QPointF(pill.left() + 24, pill.bottom() + 14),
                   f"cpu {ctx.cpu:>3.0f} · ram {ctx.ram:>3.0f} · gpu {ctx.gpu:>3.0f} · {net}")


class VDraftline:
    NAME = "DRAFTLINE"
    TAG = "wireframe blueprint + oscilloscope — precise, engineering"

    def geometry(self, av):
        w, h = 484, 252
        return QRect(av.center().x() - w // 2, av.top() + 22, w, h)

    def paint(self, p, ctx, r):
        acc = ctx.acc
        rr = r.adjusted(12, 12, -12, -12)

        # faint tinted panel + grid
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(12, 17, 28, 172))
        p.drawRect(rr)
        p.save()
        p.setClipRect(rr)
        p.setPen(QPen(QColor(120, 170, 255, 14), 1))
        gx = rr.left() + 24
        while gx < rr.right():
            p.drawLine(QPointF(gx, rr.top()), QPointF(gx, rr.bottom()))
            gx += 24
        gy = rr.top() + 24
        while gy < rr.bottom():
            p.drawLine(QPointF(rr.left(), gy), QPointF(rr.right(), gy))
            gy += 24
        p.restore()

        # outline + corner crosshairs
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 64), 1))
        p.drawRect(rr)
        p.setPen(QPen(QColor(255, 255, 255, 96), 1))
        for cx_, cy_ in ((rr.left(), rr.top()), (rr.right(), rr.top()),
                         (rr.left(), rr.bottom()), (rr.right(), rr.bottom())):
            p.drawLine(QPointF(cx_ - 9, cy_), QPointF(cx_ + 9, cy_))
            p.drawLine(QPointF(cx_, cy_ - 9), QPointF(cx_, cy_ + 9))

        # ruler ticks along top
        p.setPen(QPen(QColor(255, 255, 255, 48), 1))
        i = 0
        tx = rr.left() + 8
        while tx < rr.right() - 4:
            tl = 7 if i % 5 == 0 else 3
            p.drawLine(QPointF(tx, rr.top()), QPointF(tx, rr.top() + tl))
            tx += 8
            i += 1

        # header
        p.setFont(MONO(10))
        p.setPen(QColor(150, 165, 182, 175))
        p.drawText(QPointF(rr.left() + 14, rr.top() + 24), "OVL/07 · STATE:")
        p.setFont(MONO(11, QFont.Weight.Bold, 120))
        p.setPen(acc(240))
        p.drawText(QPointF(rr.left() + 14 + QFontMetricsF(MONO(10)).horizontalAdvance("OVL/07 · STATE: "),
                           rr.top() + 24), ctx.state_text())
        p.setFont(MONO(9))
        p.setPen(QColor(135, 150, 168, 140))
        rev = "REV C · dpr 1.25"
        p.drawText(QPointF(rr.right() - 12 - QFontMetricsF(MONO(9)).horizontalAdvance(rev),
                           rr.top() + 23), rev)

        # oscilloscope
        mid = rr.top() + rr.height() * 0.44
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.drawLine(QPointF(rr.left() + 10, mid), QPointF(rr.right() - 10, mid))
        pts = []
        w = rr.width() - 24
        for i in range(96):
            x = i / 95.0
            pts.append(QPointF(rr.left() + 12 + x * w, mid + ctx.wave(x) * 26))
        p.setPen(QPen(acc(215), 1.6))
        p.drawPolyline(QPolygonF(pts))

        # main text
        p.setFont(MONO(10, spacing=112))
        p.setPen(acc(180))
        p.drawText(QPointF(rr.left() + 14, rr.bottom() - 54), MAIN_LABEL[ctx.state()])
        p.setFont(MONO(11))
        p.setPen(QColor(230, 238, 246, 230))
        p.drawText(QRectF(rr.left() + 14, rr.bottom() - 48, rr.width() - 28, 34),
                   int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap), ctx.main_text())

        # stats bottom edge
        p.setFont(MONO(9))
        p.setPen(QColor(160, 175, 192, 160))
        net = "NET UP" if ctx.online else "NET DOWN"
        s = f"CPU {ctx.cpu:03.0f} / RAM {ctx.ram:03.0f} / GPU {ctx.gpu:03.0f} / {net}"
        p.drawText(QPointF(rr.right() - 12 - QFontMetricsF(MONO(9)).horizontalAdvance(s),
                           rr.bottom() - 6), s)


VARIANTS = [VSlate(), VReactor(), VTicker(), VGhost(), VBastion(), VCompanion(), VDraftline()]


# ==================================================================== overlay
class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("JARVIS overlay prototype")
        self.setFocusPolicy(Qt.StrongFocus)

        self._t0 = time.perf_counter()
        self.t = 0.0
        self.var_i = 0
        self.pending = None
        self.hide_done_at = 0.0

        # reveal animation (manual, evaluated per frame)
        self._rv_a, self._rv_b, self._rv_t0, self._rv_d, self._rv_e = 0.0, 0.0, 0.0, 0.001, ease_out_cubic

        # state + text
        self.state_i = 0
        self.env = ENV_TARGET["ARMED"]
        self.acc_rgb = list(ACCENT["ARMED"])
        self.state_scr = Scramble()
        self.main_scr = Scramble()
        self.word_i = 0
        self.last_word = 0.0
        self.step_i = 0
        self.step_t = 0.0
        self.last_state_change = 0.0
        self.auto = not SMOKE

        # stats
        psutil.cpu_percent(interval=None)  # prime
        self.cpu = 0.0
        self.ram = psutil.virtual_memory().percent
        self.gpu = 31.0
        self.gpu_tgt = 31.0
        self.online = False
        self._stop = False
        threading.Thread(target=self._net_loop, daemon=True).start()

        self.toast = ""
        self.toast_until = 0.0
        self._drag = None

        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(1000)
        self.stats_timer.timeout.connect(self._poll_stats)
        self.stats_timer.start()

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self.set_state(0)
        self._apply_geometry()
        self._reveal_to(1.0, 0.46, ease_out_back)
        self._show_toast()

        if SMOKE:
            self._smoke_n = 0
            self.smoke_timer = QTimer(self)
            self.smoke_timer.setInterval(500)
            self.smoke_timer.timeout.connect(self._smoke_step)
            self.smoke_timer.start()

    # ------------------------------------------------------------ time & anim
    def _now(self):
        return time.perf_counter() - self._t0

    def _reveal_to(self, target, dur, ease):
        now = self._now()
        self._rv_a = self.reveal()
        self._rv_b = target
        self._rv_t0 = now
        self._rv_d = max(dur, 0.001)
        self._rv_e = ease

    def reveal(self):
        u = (self._now() - self._rv_t0) / self._rv_d
        if u >= 1:
            return self._rv_b
        return self._rv_a + (self._rv_b - self._rv_a) * self._rv_e(u)

    # ---------------------------------------------------------------- shared
    def state(self):
        return STATES[self.state_i]

    def acc(self, alpha=255):
        r, g, b = self.acc_rgb
        return QColor(int(r), int(g), int(b), alpha)

    def state_text(self):
        return self.state_scr.text(self.t)

    def main_text(self):
        return self.main_scr.text(self.t)

    def voice(self, i, n):
        x = i / max(1, n - 1)
        t = self.t
        v = abs(math.sin(t * 2.9 + i * 0.83) * 0.55
                + math.sin(t * 5.1 + i * 1.94) * 0.30
                + math.sin(t * 8.7 + i * 3.1) * 0.15)
        bell = 0.35 + 0.65 * math.sin(math.pi * clamp(x))
        return clamp(self.env * (0.15 + 0.85 * v) * bell, 0.04, 1.0)

    def wave(self, x):
        t = self.t
        return self.env * (math.sin(t * 6.3 + x * 12.6) * 0.5
                           + math.sin(t * 9.7 + x * 23.0 + 1.7) * 0.3
                           + math.sin(t * 3.9 + x * 7.1 + 0.6) * 0.2)

    # ----------------------------------------------------------------- logic
    def set_state(self, i):
        now = self._now()
        self.state_i = i
        st = STATES[i]
        self.state_scr.set(st, now, keep_prefix=False)
        if st == "ARMED":
            self.main_scr.set(ARMED_HINT, now, keep_prefix=False)
        elif st == "HEARD":
            self.word_i = 1
            self.last_word = now
            self.main_scr.set(WORDS[0], now, keep_prefix=False)
        elif st == "WORKING":
            self.step_i = 0
            self.step_t = now
            self.main_scr.set(STEPS[0], now, keep_prefix=False)
        else:
            self.main_scr.set(REPLY, now, keep_prefix=False)
        self.last_state_change = now

    def request_switch(self, delta):
        if self.pending is not None:
            return
        self.pending = (self.var_i + delta) % len(VARIANTS)
        self._reveal_to(0.0, 0.16, ease_in_cubic)
        self.hide_done_at = self._now() + 0.17

    def _apply_geometry(self):
        av = QGuiApplication.primaryScreen().availableGeometry()
        self.setGeometry(VARIANTS[self.var_i].geometry(av))

    def _show_toast(self):
        v = VARIANTS[self.var_i]
        self.toast = f"{self.var_i + 1}/{len(VARIANTS)} · {v.NAME}"
        self.toast_until = self._now() + 1.5

    def _tick(self):
        now = self._now()
        self.t = now

        # envelope + accent easing
        self.env += (ENV_TARGET[self.state()] - self.env) * 0.075
        tgt = ACCENT[self.state()]
        for k in range(3):
            self.acc_rgb[k] += (tgt[k] - self.acc_rgb[k]) * 0.10
        self.gpu += (self.gpu_tgt - self.gpu) * 0.02

        # finish pending variant switch once hidden
        if self.pending is not None and now >= self.hide_done_at:
            self.var_i = self.pending
            self.pending = None
            self._apply_geometry()
            self._reveal_to(1.0, 0.42, ease_out_back)
            self._show_toast()

        # auto state cycle
        if self.auto and self.pending is None and now - self.last_state_change > 4.2:
            self.set_state((self.state_i + 1) % len(STATES))

        # live transcript growth (HEARD)
        if self.state() == "HEARD" and self.word_i < len(WORDS) and now - self.last_word > 0.30:
            self.word_i += 1
            self.last_word = now
            self.main_scr.set(" ".join(WORDS[:self.word_i]), now)

        # working step rotation
        if self.state() == "WORKING" and now - self.step_t > 1.6:
            self.step_i = (self.step_i + 1) % len(STEPS)
            self.step_t = now
            self.main_scr.set(STEPS[self.step_i], now, keep_prefix=False)

        self.update()

    def _poll_stats(self):
        self.cpu = psutil.cpu_percent(interval=None)
        self.ram = psutil.virtual_memory().percent
        if random.random() < 0.4:
            self.gpu_tgt = clamp(self.gpu_tgt + random.uniform(-14, 14), 6, 88)

    def _net_loop(self):
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

    def _smoke_step(self):
        self._smoke_n += 1
        self.set_state((self.state_i + 1) % len(STATES))
        if self._smoke_n % 3 == 0:
            self.request_switch(+1)
        if self._smoke_n >= 24:
            print("SMOKE OK: all 7 variants and 4 states cycled with live paints")
            QApplication.quit()

    # ----------------------------------------------------------------- paint
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        a = self.reveal()
        op = clamp(a)
        if op > 0.004:
            p.save()
            w, h = self.width(), self.height()
            cx, cy = w / 2.0, h / 2.0
            s = 0.90 + 0.10 * a
            p.translate(cx, cy + (1 - min(a, 1.0)) * 16)
            p.scale(s, s)
            p.translate(-cx, -cy)
            p.setOpacity(op)
            VARIANTS[self.var_i].paint(p, self, QRectF(0, 0, w, h))
            p.restore()

        # variant-name toast
        left = self.toast_until - self.t
        if left > 0:
            fade = clamp(left / 0.4)
            p.setOpacity(fade)
            f = MONO(10, QFont.Weight.Bold, 118)
            fm = QFontMetricsF(f)
            tw = fm.horizontalAdvance(self.toast)
            pr = QRectF(self.width() / 2 - tw / 2 - 12, 6, tw + 24, 22)
            p.setPen(QPen(QColor(255, 255, 255, 50), 1))
            p.setBrush(QColor(6, 8, 12, 215))
            p.drawRoundedRect(pr, 11, 11)
            p.setFont(f)
            p.setPen(self.acc(240))
            p.drawText(pr, int(Qt.AlignCenter), self.toast)
            p.setOpacity(1.0)
        p.end()

    # ------------------------------------------------------------------ input
    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Escape:
            self.close()
        elif k == Qt.Key_Right:
            self.request_switch(+1)
        elif k == Qt.Key_Left:
            self.request_switch(-1)
        elif k == Qt.Key_Space:
            self.set_state((self.state_i + 1) % len(STATES))
        elif k == Qt.Key_A:
            self.auto = not self.auto
            self.toast = f"auto-cycle {'ON' if self.auto else 'OFF'}"
            self.toast_until = self._now() + 1.2
        else:
            super().keyPressEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if self._drag is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _ev):
        self._drag = None

    def closeEvent(self, ev):
        self._stop = True
        super().closeEvent(ev)


def main():
    app = QApplication(sys.argv)
    ov = Overlay()
    ov.show()
    ov.raise_()
    ov.activateWindow()
    print("JARVIS overlay prototype - Left/Right variant, Space state, "
          "A auto-cycle, Esc quit. Drag to move.", flush=True)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
