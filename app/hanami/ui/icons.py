"""Hanami's icon: a deep-rose cherry blossom on a blossom-pink tile."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap, QTransform

# The suite's shared shape, so Hanami sits beside Homework Hub, Grabbit,
# Dropshift and Keytap as one of a set: a tile in blossom pink filling the
# whole square, corners rounded to 42/192 of its width, and one mark in deep
# rose - white would vanish on the pale pink.
#
# The colours are constants on purpose: make_icon.py bakes this icon into the
# exe at build time, and a colour taken from the palette there would be
# whatever accent Windows happened to have that day.
APP_ICON_COLOR = '#ffd1dc'
APP_ICON_MARK = '#c2255c'
APP_ICON_CORNER = 42 / 192

# The mark is a five-petalled cherry blossom, one petal pointing up. In units
# of a 64-wide tile: petal tips at radius r, petal half-width w, the notch at
# each tip n deep and the two lobes either side of it s apart; a centre of
# tile pink (radius c) with five rose stamen dots on a ring (dot, ring).
# Small icons get a plainer flower - a notch and stamens would only blur.
_MARK_LARGE = dict(r=19, w=9.5, n=3.2, s=2.6, c=6.0, dot=0.95, ring=3.7)
_MARK_MEDIUM = dict(r=19.5, w=10, n=3.0, s=2.6, c=4.6, dot=0, ring=0)    # 24-48px
_MARK_SMALL = dict(r=20, w=10.5, n=0, s=0, c=4.6, dot=0, ring=0)          # 16-20px


def _mark(size: int) -> dict:
    if size <= 20:
        return _MARK_SMALL
    if size <= 48:
        return _MARK_MEDIUM
    return _MARK_LARGE


def _petal(k: dict) -> QPainterPath:
    """One petal pointing straight up from the centre (0, 0)."""
    r, w, n, s = k['r'], k['w'], k['n'], k['s']
    path = QPainterPath(QPointF(0, -2))
    if n:
        path.cubicTo(QPointF(w * 0.9, -r * 0.30), QPointF(w * 1.05, -r * 0.88), QPointF(s, -r))
        path.lineTo(QPointF(0, -r + n))
        path.lineTo(QPointF(-s, -r))
        path.cubicTo(QPointF(-w * 1.05, -r * 0.88), QPointF(-w * 0.9, -r * 0.30), QPointF(0, -2))
    else:
        path.cubicTo(QPointF(w * 0.9, -r * 0.30), QPointF(w * 1.05, -r * 1.02), QPointF(0, -r))
        path.cubicTo(QPointF(-w * 1.05, -r * 1.02), QPointF(-w * 0.9, -r * 0.30), QPointF(0, -2))
    path.closeSubpath()
    return path


def render_app_icon(size: int) -> QPixmap:
    """The app icon at one size, drawn for that size rather than scaled."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 64.0, size / 64.0)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(APP_ICON_COLOR))
    corner = 64 * APP_ICON_CORNER
    painter.drawRoundedRect(QRectF(0, 0, 64, 64), corner, corner)

    k = _mark(size)
    centre = QPointF(32, 33)        # a hair low: the top petal makes the flower look high otherwise
    petal = _petal(k)
    painter.setBrush(QColor(APP_ICON_MARK))
    for i in range(5):
        turn = QTransform().translate(centre.x(), centre.y()).rotate(72 * i)
        painter.drawPath(turn.map(petal))
    # The heart of the flower, punched in the tile's own pink, with its stamens.
    painter.setBrush(QColor(APP_ICON_COLOR))
    painter.drawEllipse(centre, k['c'], k['c'])
    if k['dot']:
        painter.setBrush(QColor(APP_ICON_MARK))
        painter.drawEllipse(centre, k['dot'] * 1.3, k['dot'] * 1.3)
        for i in range(5):
            angle = math.radians(72 * i + 36 - 90)     # between the petals
            dot = QPointF(centre.x() + k['ring'] * math.cos(angle), centre.y() + k['ring'] * math.sin(angle))
            painter.drawEllipse(dot, k['dot'], k['dot'])
    painter.end()
    return pixmap


ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def app_icon() -> QIcon:
    """The tray, window and launcher icon - and the one in the exe."""
    result = QIcon()
    for size in ICON_SIZES:
        result.addPixmap(render_app_icon(size))
    return result
