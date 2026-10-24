"""The edge panel: rest the pointer on the little tab at the screen's edge (or click it), and a pane
of glass slides out there over a photo of blossom, holding the suite's apps and the sound switch.
The tab shows where the panel is, as Samsung's edge panel's does. It sits in the middle of the edge
until it is moved - the tab dragged up or down, or the handle along the panel's top (place: where
along the edge its middle is, as a share of the screen's height). The tab keeps out of the way of
games and anything else full screen (quiet), and of the panel itself while that is out.

Only an edge with no screen beyond it counts - the pointer can rest there, and passing through to
another screen never brings the panel out - and the pointer has to stay a moment (DWELL), with no
button held, and not over a game or anything else full screen (quiet, as Hanami says). It slides
away once the pointer has left it for a moment (LEAVE), and after a choice in it.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QToolTip, QVBoxLayout, QWidget

from .. import win32
from . import icons, theme
from .sound import SoundToggle

PHOTO = str(Path(__file__).with_name('panel.jpg'))     # Yan Liu's blossom, on Unsplash
WIDTH = 106
ICON = 48
MARGIN = 10             # between the panel and the screen's edge
DWELL = 0.3             # s the pointer rests at the edge before the panel comes out
LEAVE = 0.45            # s after the pointer leaves it before it slides away
WATCH_MS = 60
TAB = 10, 76            # the tab's window, at the edge; its bar is narrower, a little in from the edge
TAB_EVERY = 0.4         # s between looks at whether the tab should show, and where
EDGES = {'right': 'Right', 'left': 'Left'}


def pointer() -> QPoint:
    """Where the pointer is (a function of its own, for tests to stand in)."""
    return QCursor.pos()


def at_edge(point: QPoint, edge: str) -> QRect | None:
    """The screen whose edge the pointer rests on, with no screen beyond - or None."""
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
    return g if on and QGuiApplication.screenAt(beyond) is None else None


def home_screen(edge: str) -> QRect | None:
    """The screen the tab sits on: one whose edge on that side has no screen beyond - the main
    screen if it is one."""
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()

    def outer(screen) -> bool:
        g = screen.geometry()
        x = g.right() + 2 if edge == 'right' else g.left() - 2
        return QGuiApplication.screenAt(QPoint(x, g.center().y())) is None
    found = [s for s in screens if outer(s)]
    if not found:
        return None
    return (primary if primary in found else found[0]).geometry()


class _EdgeTab(QWidget):
    """The little tab at the screen's edge: where the panel is. Clicked, it brings the panel out;
    dragged, it moves up or down the edge."""
    clicked = Signal()
    dragged = Signal(int)           # where its middle would be, as the pointer moves
    dropped = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(*TAB)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Hanami - click, or drag to move')
        self.edge = 'right'
        self._press: float | None = None
        self._moving = False
        self._hover = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press, self._moving = event.globalPosition().y(), False

    def mouseMoveEvent(self, event):
        if self._press is None:
            return
        y = event.globalPosition().y()
        if not self._moving and abs(y - self._press) > 4:
            self._moving = True
            self.setCursor(Qt.SizeVerCursor)
        if self._moving:
            self.dragged.emit(round(y))

    def mouseReleaseEvent(self, event):
        if self._press is None or event.button() != Qt.LeftButton:
            return
        moved, self._press, self._moving = self._moving, None, False
        self.setCursor(Qt.PointingHandCursor)
        if moved:
            self.dropped.emit()
        else:
            self.clicked.emit()

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def paintEvent(self, event):
        c = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        lit = self._hover or self._moving
        width = 7 if lit else 5
        x = self.width() - width - 2 if self.edge == 'right' else 2
        bar = QRectF(x, 1, width, self.height() - 2)
        fill = QColor(theme.ACCENT)
        fill.setAlpha(255 if lit else 200)
        painter.setPen(QPen(c.edge, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(bar, width / 2, width / 2)
        painter.end()


class _Handle(QWidget):
    """The grip along the panel's top: dragged, the panel follows up or down the edge."""
    dragged = Signal(int)           # where the panel's top would be, as the pointer moves
    dropped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(WIDTH - 24, 14)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip('Drag to move')
        self.setAccessibleName('Move the panel')
        self._grab: float | None = None
        self._hover = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._grab = event.globalPosition().y() - self.window().y()

    def mouseMoveEvent(self, event):
        if self._grab is not None:
            self.dragged.emit(round(event.globalPosition().y() - self._grab))

    def mouseReleaseEvent(self, event):
        if self._grab is not None and event.button() == Qt.LeftButton:
            self._grab = None
            self.dropped.emit()

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def paintEvent(self, event):
        c = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        color = QColor(c.text if self._hover or self._grab is not None else c.dim)
        color.setAlpha(230 if self._hover or self._grab is not None else 170)
        painter.setBrush(color)
        grip = QRectF(0, 0, 30, 4)
        grip.moveCenter(QPointF(self.width() / 2, self.height() / 2))
        painter.drawRoundedRect(grip, 2, 2)
        painter.end()


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
    moved = Signal(float)               # dropped by its handle: where along the edge it is now (place)
    output_clicked = Signal(str)        # 'speakers' or 'headphones'
    showing = Signal()                  # about to come out: the apps and the sound, as they are now

    def __init__(self, quiet=lambda: False):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        theme.frost(self, fade=False)               # it slides out instead
        self.setFixedWidth(WIDTH)
        self.quiet = quiet
        self.edge: str | None = None
        self.place = 0.5
        self._dragging = False
        self._photo = QPixmap(PHOTO)
        self._resting_since: float | None = None
        self._left_at: float | None = None
        self._sliding: QPropertyAnimation | None = None
        self._leaving = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 14)
        layout.setSpacing(8)
        self.handle = _Handle()
        self.handle.dragged.connect(self._drag_to)
        self.handle.dropped.connect(self._dropped)
        layout.addWidget(self.handle, 0, Qt.AlignHCenter)
        layout.addSpacing(-4)
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
        self.tab = _EdgeTab()
        self.tab.clicked.connect(self._tab_clicked)
        self.tab.dragged.connect(self._tab_dragged)
        self.tab.dropped.connect(self._tab_dropped)
        self._tab_looked = 0.0
        self._tab_dragging = False

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
        self._tab_looked = 0.0
        if self.edge:
            self.tab.edge = self.edge
            self._watch.start()
            self._show_tab()
        else:
            self._watch.stop()
            self.tab.hide()
            if self.isVisible():
                self.hide()

    # ------------------------------------------------------------------ the tab

    def allowed(self) -> bool:
        """Whether it may come out now: not over a game or anything full screen, nor mid-drag."""
        return not self.quiet() and not win32.buttons_down()

    def _middle(self, screen: QRect, height: int) -> int:
        """Where along that screen's edge something of that height has its middle, at place - all
        of it on the screen."""
        middle = screen.top() + self.place * screen.height()
        return round(max(screen.top() + MARGIN + height / 2, min(middle, screen.bottom() + 1 - MARGIN - height / 2)))

    def _show_tab(self) -> None:
        """The tab where the panel is - unless the panel is out, or something full screen is in front."""
        home = home_screen(self.edge) if self.edge else None
        if home is None or self.isVisible() or self.quiet():
            self.tab.hide()
            return
        x = home.right() + 1 - TAB[0] if self.edge == 'right' else home.left()
        place = QPoint(x, self._middle(home, TAB[1]) - TAB[1] // 2)
        if self.tab.pos() != place:
            self.tab.move(place)
        if not self.tab.isVisible():
            self.tab.show()

    def _tab_clicked(self) -> None:
        home = home_screen(self.edge) if self.edge else None
        if home is not None and not self.isVisible() and not self.quiet():
            self.slide_out(home)

    def _tab_dragged(self, middle: int) -> None:
        home = home_screen(self.edge) if self.edge else None
        if home is None:
            return
        self._tab_dragging = True
        self._resting_since = None
        top = max(home.top() + MARGIN, min(middle - TAB[1] // 2, home.bottom() + 1 - MARGIN - TAB[1]))
        self.tab.move(self.tab.x(), top)

    def _tab_dropped(self) -> None:
        self._tab_dragging = False
        home = home_screen(self.edge) if self.edge else None
        if home is None:
            return
        self.place = max(0.0, min(1.0, (self.tab.y() + TAB[1] / 2 - home.top()) / home.height()))
        self.moved.emit(self.place)

    def _look(self) -> None:
        now = time.monotonic()
        point = pointer()
        if not self._tab_dragging and now - self._tab_looked >= TAB_EVERY:
            self._tab_looked = now
            self._show_tab()
        if self._dragging or self._tab_dragging:
            return
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
        top, bottom = self._zone(screen) if screen is not None else (0, -1)
        if not top <= point.y() <= bottom:
            self._resting_since = None
            return
        if self._resting_since is None:
            self._resting_since = now
        elif now - self._resting_since >= DWELL and self.allowed():
            self._resting_since = None
            self.slide_out(screen)

    def _height(self, screen: QRect) -> int:
        return min(max(self.height(), self.sizeHint().height()), screen.height() - 2 * MARGIN)

    def _top(self, screen: QRect, height: int) -> int:
        """Where its top goes on that screen, its middle at place - all of it on the screen."""
        return round(self._middle(screen, height) - height / 2)

    def _zone(self, screen: QRect) -> tuple[int, int]:
        """Where along the edge resting brings it out: around the tab - an eighth of the screen's
        height at least, so it is easy to hit."""
        middle = self._middle(screen, TAB[1])
        reach = max(TAB[1] + 40, screen.height() // 8)
        return round(middle - reach / 2), round(middle + reach / 2)

    def _places(self, screen: QRect) -> tuple[QPoint, QPoint]:
        """Where it rests, and where it slides from - just beyond the edge."""
        top = self._top(screen, self._height(screen))
        if self.edge == 'left':
            return QPoint(screen.left() + MARGIN, top), QPoint(screen.left() - WIDTH - 2, top)
        return QPoint(screen.right() - WIDTH - MARGIN + 1, top), QPoint(screen.right() + 2, top)

    def _drag_to(self, top: int) -> None:
        """Its handle dragged: up or down the edge, staying on the screen."""
        screen = QGuiApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            return
        g = screen.geometry()
        self._dragging = True
        self._left_at = None
        self.move(self.x(), max(g.top() + MARGIN, min(top, g.bottom() + 1 - self.height() - MARGIN)))

    def _dropped(self) -> None:
        self._dragging = False
        screen = QGuiApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            return
        g = screen.geometry()
        self.place = max(0.0, min(1.0, (self.y() + self.height() / 2 - g.top()) / g.height()))
        self.moved.emit(self.place)

    def slide_out(self, screen: QRect) -> None:
        self.showing.emit()
        self.tab.hide()
        self.adjustSize()
        rest, start = self._places(screen)
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
            self._show_tab()
            return
        _, away = self._places(screen.geometry())
        self._slide(self.pos(), QPoint(away.x(), self.y()), 200, QEasingCurve.InCubic, then=self._gone)

    def _gone(self) -> None:
        self.hide()
        self.setWindowOpacity(1.0)
        self._leaving = False
        self._show_tab()

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
