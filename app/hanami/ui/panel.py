"""The edge panel: rest the pointer at the middle of the screen's edge, and a pane of glass slides
out there over a photo of blossom, holding the suite's apps and the sound switch.

Only an edge with no screen beyond it counts - the pointer can rest there, and passing through to
another screen never brings the panel out - and the pointer has to stay a moment (DWELL), with no
button held. Hanami says when the panel may come out at all (allowed): not over a game or anything
else full screen. It slides away once the pointer has left it for a moment (LEAVE), and after a
choice in it.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QToolTip, QVBoxLayout, QWidget

from . import icons, theme
from .sound import SoundToggle

PHOTO = str(Path(__file__).with_name('panel.jpg'))     # Yan Liu's blossom, on Unsplash
WIDTH = 106
ICON = 48
MARGIN = 10             # between the panel and the screen's edge
DWELL = 0.3             # s the pointer rests at the edge before the panel comes out
LEAVE = 0.45            # s after the pointer leaves it before it slides away
WATCH_MS = 60
REACH = 0.25            # the part of the edge that counts: all but this share at either end
EDGES = {'right': 'Right', 'left': 'Left'}


def pointer() -> QPoint:
    """Where the pointer is (a function of its own, for tests to stand in)."""
    return QCursor.pos()


def at_edge(point: QPoint, edge: str) -> QRect | None:
    """The screen whose edge the pointer rests on, at the middle part of it, with no screen beyond -
    or None."""
    screen = QGuiApplication.screenAt(point)
    if screen is None:
        return None
    g = screen.geometry()
    if edge == 'right':
        on, beyond = point.x() >= g.right() - 1, QPoint(g.right() + 2, point.y())
    elif edge == 'left':
        on, beyond = point.x() <= g.left() + 1, QPoint(g.left() - 2, point.y())
    else:
        return None
    middle = g.top() + g.height() * REACH <= point.y() <= g.bottom() - g.height() * REACH
    return g if on and middle and QGuiApplication.screenAt(beyond) is None else None


class _AppButton(QWidget):
    """One app: its icon, lifting as the pointer comes over it, a dot under it while it runs."""
    clicked = Signal(str)

    def __init__(self, name: str, icon: QPixmap, running: bool, parent=None):
        super().__init__(parent)
        self.name, self.icon, self.running = name, icon, running
        self.setFixedSize(WIDTH - 2 * 12, ICON + 14)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(name)
        self._lift = 0.0
        self._moving: QVariantAnimation | None = None

    def _to(self, value: float) -> None:
        if not theme.motion_on():
            self._lift = value
            self.update()
            return
        if self._moving is not None:
            self._moving.stop()
        lift = QVariantAnimation(self)
        lift.setDuration(160 if value else 260)
        lift.setStartValue(self._lift)
        lift.setEndValue(value)
        lift.setEasingCurve(QEasingCurve.OutCubic)
        lift.valueChanged.connect(lambda v: (setattr(self, '_lift', float(v)), self.update()))
        self._moving = lift
        lift.start()

    def enterEvent(self, event):
        self._to(1.0)
        QToolTip.showText(self.mapToGlobal(QPoint(0, self.height() // 2)), self.name, self)

    def leaveEvent(self, event):
        self._to(0.0)
        QToolTip.hideText()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.name)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        size = ICON * (1 + 0.1 * self._lift)
        box = QRectF((self.width() - size) / 2, 4 - 3 * self._lift + (ICON - size) / 2, size, size)
        theme.paint_shadow(painter, box, size * 42 / 192, 6, QColor(60, 20, 40, int(50 + 40 * self._lift)))
        painter.drawPixmap(box, self.icon, QRectF(self.icon.rect()))
        if self.running:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.ink()))
            painter.drawEllipse(QPointF(self.width() / 2, self.height() - 4), 2.5, 2.5)
        painter.end()


class EdgePanel(QWidget):
    open_app = Signal(str)
    open_hanami = Signal()
    output_clicked = Signal(str)        # 'speakers' or 'headphones'
    showing = Signal()                  # about to come out: the apps and the sound, as they are now

    def __init__(self, allowed=lambda: True):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        theme.frost(self, fade=False)               # it slides out instead
        self.setFixedWidth(WIDTH)
        self.allowed = allowed
        self.edge: str | None = None
        self._photo = QPixmap(PHOTO)
        self._resting_since: float | None = None
        self._left_at: float | None = None
        self._sliding: QPropertyAnimation | None = None
        self._leaving = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(8)
        self.hanami = _AppButton('Hanami', icons.render_app_icon(ICON), False)
        self.hanami.clicked.connect(lambda _: self._chose(self.open_hanami.emit))
        layout.addWidget(self.hanami, 0, Qt.AlignHCenter)
        self._apps = QVBoxLayout()
        self._apps.setSpacing(4)
        layout.addLayout(self._apps)
        layout.addSpacing(6)
        self.sound = SoundToggle()
        self.sound.chosen.connect(self.output_clicked)
        layout.addWidget(self.sound, 0, Qt.AlignHCenter)
        self.buttons: dict[str, _AppButton] = {}

        self._watch = QTimer(self)
        self._watch.setInterval(WATCH_MS)
        self._watch.timeout.connect(self._look)

    # ------------------------------------------------------------------ what it holds

    def show_apps(self, apps: list[tuple[str, QPixmap, bool]]) -> None:
        """The apps on this PC: (name, icon, running)."""
        for button in self.buttons.values():
            self._apps.removeWidget(button)
            button.deleteLater()
        self.buttons = {}
        for name, icon, running in apps:
            button = _AppButton(name, icon, running)
            button.clicked.connect(lambda n: self._chose(lambda: self.open_app.emit(n)))
            self.buttons[name] = button
            self._apps.addWidget(button, 0, Qt.AlignHCenter)
        self.adjustSize()

    def _chose(self, then) -> None:
        then()
        self.slide_away()

    # ------------------------------------------------------------------ the edge

    def set_edge(self, edge: str | None) -> None:
        """Watch that edge of the screen ('left' or 'right'), or none."""
        self.edge = edge if edge in EDGES else None
        self._resting_since = None
        if self.edge:
            self._watch.start()
        else:
            self._watch.stop()
            if self.isVisible():
                self.hide()

    def _look(self) -> None:
        now = time.monotonic()
        point = pointer()
        if self.isVisible() and not self._leaving:
            near = self.frameGeometry().adjusted(-24, -24, 24, 24)
            if near.contains(point) or at_edge(point, self.edge) is not None:
                self._left_at = None
            elif self._left_at is None:
                self._left_at = now
            elif now - self._left_at >= LEAVE:
                self.slide_away()
            return
        if self.isVisible():
            return
        screen = at_edge(point, self.edge)
        if screen is None:
            self._resting_since = None
            return
        if self._resting_since is None:
            self._resting_since = now
        elif now - self._resting_since >= DWELL and self.allowed():
            self._resting_since = None
            self.slide_out(screen, point.y())

    def _places(self, screen: QRect, y: int) -> tuple[QPoint, QPoint]:
        """Where it rests, and where it slides from - just beyond the edge."""
        height = self.sizeHint().height()
        top = max(screen.top() + MARGIN, min(y - height // 2, screen.bottom() - height - MARGIN))
        if self.edge == 'left':
            return QPoint(screen.left() + MARGIN, top), QPoint(screen.left() - WIDTH - 2, top)
        return QPoint(screen.right() - WIDTH - MARGIN + 1, top), QPoint(screen.right() + 2, top)

    def slide_out(self, screen: QRect, y: int) -> None:
        self.showing.emit()
        self.adjustSize()
        rest, start = self._places(screen, y)
        self._left_at = None
        self._leaving = False
        if not theme.motion_on():
            self.move(rest)
            self.show()
            return
        self.move(start)
        self.setWindowOpacity(0.0)
        self.show()
        self._slide(start, rest, 260, QEasingCurve.OutBack if theme.look() == 'liquid' else QEasingCurve.OutCubic)

    def slide_away(self) -> None:
        if not self.isVisible() or self._leaving:
            return
        self._leaving = True
        QToolTip.hideText()
        screen = QGuiApplication.screenAt(self.frameGeometry().center())
        if not theme.motion_on() or screen is None:
            self.hide()
            self._leaving = False
            return
        _, away = self._places(screen.geometry(), self.frameGeometry().center().y())
        self._slide(self.pos(), QPoint(away.x(), self.y()), 200, QEasingCurve.InCubic, then=self._gone)

    def _gone(self) -> None:
        self.hide()
        self.setWindowOpacity(1.0)
        self._leaving = False

    def _slide(self, start: QPoint, end: QPoint, ms: int, curve, then=None) -> None:
        if self._sliding is not None:
            self._sliding.stop()
        slide = QPropertyAnimation(self, b'pos', self)
        slide.setDuration(ms)
        slide.setStartValue(start)
        slide.setEndValue(end)
        slide.setEasingCurve(curve)
        coming = then is None
        slide.valueChanged.connect(lambda _: self.setWindowOpacity(
            min(1.0, slide.currentTime() / (ms * 0.6)) if coming else max(0.0, 1 - slide.currentTime() / ms)))
        if then is not None:
            slide.finished.connect(then)
        else:
            slide.finished.connect(lambda: self.setWindowOpacity(1.0))
        self._sliding = slide
        slide.start()

    # ------------------------------------------------------------------ drawing

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        radius = theme.LIQUID_RADIUS if theme.look() == 'liquid' and theme.glass_on() else theme.GLASS_RADIUS
        theme.paint_glass(painter, rect, radius)
        inner = rect.adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(inner, radius - 1, radius - 1)
        dark = theme.is_dark()
        if not self._photo.isNull():
            painter.save()
            painter.setClipPath(path)
            painter.setOpacity(0.5 if dark else 0.7)
            photo = self._photo.size().scaled(inner.size().toSize(), Qt.KeepAspectRatioByExpanding)
            place = QRectF(inner.center().x() - photo.width() / 2, inner.center().y() - photo.height() / 2,
                           photo.width(), photo.height())
            painter.drawPixmap(place, self._photo, QRectF(self._photo.rect()))
            painter.restore()
        painter.fillPath(path, QColor(30, 24, 36, 90) if dark else QColor(255, 255, 255, 40))
        painter.setPen(QPen(QColor(255, 255, 255, 90 if dark else 200), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        painter.end()
