"""The edge panel: rest the pointer on the little tab at the screen's edge (or click it), and a pane
of glass slides out there over a photo of blossom. It has three pages, turned with the scroll wheel
(or the dots along its bottom, showing which is in sight): the suite's apps, what is pinned to it
in Settings (programs, files, folders, websites), and how busy the PC is (stats.py) - sampled once a
second only while that page is in sight. Under them, on every page, the sound button and the
microphone's mute button.

The tab shows where the panel is, as Samsung's edge panel's does. It sits in the middle of the edge
until it is moved - the tab dragged up or down, or the handle along the panel's top (place: where
along the edge its middle is, as a share of the screen's height). The tab keeps out of the way of
games and anything else full screen (quiet), and of the panel itself while that is out.

The pointer need not be right against the edge: anywhere within NEAR of it, beside where the panel
sits, will do. Only an edge with no screen beyond it counts - passing through to another screen
never brings the panel out - and the pointer has to stay a moment (DWELL), with no button held,
and not over a game or anything else full screen (quiet, as Hanami says). While one of those is
in front, the panel doesn't watch the pointer at all: it only looks, now and then (QUIET_EVERY),
for it to go. It slides away once the pointer has left it for a moment (LEAVE), and after a
choice in it.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QToolTip, QVBoxLayout, QWidget

from .. import win32
from . import icons, theme
from .pins import MOST as PINS_MOST
from .sound import MicButton, SoundToggle

PHOTO = str(Path(__file__).with_name('panel.jpg'))     # Yan Liu's blossom, on Unsplash
WIDTH = 140
ICON = 48
INNER = WIDTH - 2 * 12  # within its margins
PIN_ICON = 40
PIN_TILE = (INNER - 4) // 2
PAGES = ('apps', 'pinned', 'stats')    # the Hanami suite, shortcuts, stats: those chosen are shown, in this order
STATS_EVERY = 1000      # ms between samples, while the stats page is in sight
MARGIN = 10             # between the panel and the screen's edge
NEAR = 48               # px in from the screen's edge that count as at it
DWELL = 0.3             # s the pointer rests at the edge before the panel comes out
LEAVE = 0.45            # s after the pointer leaves it before it slides away
WATCH_MS = 60
TAB_LOOK = 76, 5, 30    # the tab as it comes: its length and thickness (px), how opaque at rest (%)
TAB_LIMITS = (40, 240), (3, 12), (10, 100)
TAB_EVERY = 0.4         # s between looks at whether the tab should show, and where
QUIET_EVERY = 1000      # ms between looks at whether a game, or anything full screen, has left the front
EDGES = {'right': 'Right', 'left': 'Left'}


def pointer() -> QPoint:
    """Where the pointer is (a function of its own, for tests to stand in)."""
    return QCursor.pos()


def at_edge(point: QPoint, edge: str) -> QRect | None:
    """The screen whose edge the pointer is at (within NEAR of it), with no screen beyond - or
    None."""
    screen = QGuiApplication.screenAt(point)
    if screen is None:
        return None
    g = screen.geometry()
    if edge == 'right':
        on, beyond = point.x() > g.right() - NEAR, QPoint(g.right() + 2, point.y())
    elif edge == 'left':
        on, beyond = point.x() < g.left() + NEAR, QPoint(g.left() - 2, point.y())
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
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Hanami - click, or drag to move')
        self.edge = 'right'
        self._press: float | None = None
        self._moving = False
        self._hover = False
        self.set_look(*TAB_LOOK)

    def set_look(self, length: int, thickness: int, opacity: int) -> None:
        """Its length and its bar's thickness (px), and how opaque it is at rest (%) - full, and
        a little thicker, while the pointer is on it. Its window leaves the bar room to thicken,
        and a little gap at the screen's edge."""
        self.thickness, self.opacity = thickness, opacity
        self.setFixedSize(thickness + 5, length)
        self.update()

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
        width = self.thickness + 2 if lit else self.thickness
        x = self.width() - width - 2 if self.edge == 'right' else 2
        bar = QRectF(x, 1, width, self.height() - 2)
        share = 1.0 if lit else self.opacity / 100
        fill = QColor(theme.ACCENT)
        fill.setAlphaF(share)
        edge = QColor(c.edge)
        edge.setAlphaF(edge.alphaF() * share)
        painter.setPen(QPen(edge, 1))
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
        held = self._hover or self._grab is not None
        color = QColor(c.text if held else c.dim)
        color.setAlpha(230 if held else 170)
        painter.setBrush(color)
        grip = QRectF(0, 0, 30, 4)
        grip.moveCenter(QPointF(self.width() / 2, self.height() / 2))
        painter.drawRoundedRect(grip, 2, 2)
        painter.end()


class _AppButton(QWidget):
    """One app (or something pinned): its icon, lifting as the pointer comes over it, a dot under it
    while it runs."""
    clicked = Signal(str)

    def __init__(self, name: str, icon: QPixmap, running: bool, parent=None, size: int = ICON, width: int = INNER):
        super().__init__(parent)
        self.name, self.icon, self.running, self.size_ = name, icon, running, size
        self.setFixedSize(width, size + 14)
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

    def leaveEvent(self, event):
        self._to(0.0)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.name)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        size = self.size_ * (1 + 0.1 * self._lift)
        box = QRectF((self.width() - size) / 2, 4 - 3 * self._lift + (self.size_ - size) / 2, size, size)
        theme.paint_shadow(painter, box, size * 42 / 192, 6, QColor(60, 20, 40, int(50 + 40 * self._lift)))
        painter.drawPixmap(box, self.icon, QRectF(self.icon.rect()))
        if self.running:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.ink()))
            painter.drawEllipse(QPointF(self.width() / 2, self.height() - 4), 2.5, 2.5)
        painter.end()


class _AddButton(QWidget):
    """After what is pinned: a plus, opening Settings to pin something more."""
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(PIN_TILE, PIN_ICON + 14)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName('Pin something')
        self._hover = False

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, event):
        c = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF((self.width() - PIN_ICON) / 2 + 0.5, 4.5, PIN_ICON - 1, PIN_ICON - 1)
        color = QColor(c.text if self._hover else c.dim)
        color.setAlphaF(0.9 if self._hover else 0.6)
        painter.setPen(QPen(color, 1.2, Qt.DashLine))
        painter.setBrush(QColor(255, 255, 255, 30) if self._hover else Qt.NoBrush)
        painter.drawRoundedRect(box, PIN_ICON * 42 / 192, PIN_ICON * 42 / 192)
        painter.setPen(QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap))
        middle, arm = box.center(), PIN_ICON * 0.18
        painter.drawLine(QPointF(middle.x() - arm, middle.y()), QPointF(middle.x() + arm, middle.y()))
        painter.drawLine(QPointF(middle.x(), middle.y() - arm), QPointF(middle.x(), middle.y() + arm))
        painter.end()


class _Stat(QWidget):
    """One of the PC's stats: its name and value on a line, and under them (bar) a bar showing how
    busy or how full - gliding to each new value."""

    def __init__(self, name: str, bar: bool = True):
        super().__init__()
        self.name, self.bar = name, bar
        self.value, self.share = '–', 0.0
        self._glide: QVariantAnimation | None = None
        self.setFixedSize(INNER, 30 if bar else 20)
        self.setAccessibleName(name)

    def set_value(self, value: str, share: float | None = None) -> None:
        self.value = value
        self.setAccessibleDescription(value)
        if share is None or not self.bar:
            self.update()
            return
        share = max(0.0, min(1.0, share))
        if self._glide is not None:
            self._glide.stop()
        if not theme.motion_on() or not self.isVisible():
            self.share = share
            self.update()
            return
        glide = self._glide = QVariantAnimation(self)
        glide.setDuration(400)
        glide.setEasingCurve(QEasingCurve.OutCubic)
        glide.setStartValue(self.share)
        glide.setEndValue(share)
        glide.valueChanged.connect(lambda v: (setattr(self, 'share', float(v)), self.update()))
        glide.start()

    def paintEvent(self, event):
        c = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        line = QRectF(0, 0, self.width(), 18)
        painter.setFont(theme.font(8.5))
        painter.setPen(c.dim)
        painter.drawText(line, Qt.AlignLeft | Qt.AlignVCenter, self.name)
        painter.setFont(theme.font(9.5, QFont.DemiBold))
        painter.setPen(c.text)
        painter.drawText(line, Qt.AlignRight | Qt.AlignVCenter, self.value)
        if self.bar:
            track = QRectF(0, 22, self.width(), 5)
            painter.setPen(Qt.NoPen)
            painter.setBrush(c.border)
            painter.drawRoundedRect(track, 2.5, 2.5)
            if self.share > 0:
                painter.setBrush(QColor(theme.ACCENT))
                painter.drawRoundedRect(QRectF(track.x(), track.y(), max(5.0, track.width() * self.share), 5), 2.5, 2.5)
        painter.end()


class _Pages(QWidget):
    """The panel's pages, side by side: one in sight, the next sliding in from beside it - only
    those turned on (shown: their indexes, in order). As big as the biggest of them, so the panel
    keeps its size from page to page."""
    changed = Signal(int)               # the page now in sight, by its place among those shown

    def __init__(self):
        super().__init__()
        self.pages: list[QWidget] = []
        self.shown: list[int] = []
        self.current = 0                # the page in sight, by its index among them all
        self._slide: QVariantAnimation | None = None

    def add(self, page: QWidget) -> None:
        page.setParent(self)
        page.setVisible(not self.pages)
        self.shown.append(len(self.pages))
        self.pages.append(page)

    def show_only(self, shown: list[int]) -> None:
        """Have only these pages (indexes, in order) - the one in sight stays, if it is one of them."""
        self.shown = [index for index in shown if 0 <= index < len(self.pages)] or [0]
        if self.current not in self.shown:
            self.current = self.shown[0]
        self.refit()

    @property
    def position(self) -> int:
        """The page in sight, by its place among those shown."""
        return self.shown.index(self.current) if self.current in self.shown else 0

    def sizeHint(self) -> QSize:
        hints = [self.pages[index].sizeHint() for index in self.shown] or [QSize(0, 0)]
        return QSize(max(h.width() for h in hints), max(h.height() for h in hints))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def refit(self) -> None:
        """A page's contents changed: the pages take the size of the biggest again. (Each page's
        layout reckons its size now - left to itself, it would only once Qt next gets round to it.)"""
        for page in self.pages:
            if page.layout() is not None:
                page.layout().invalidate()
                page.layout().activate()
        self.updateGeometry()
        self._place()

    def resizeEvent(self, event):
        self._place()

    def _place(self) -> None:
        if self._slide is not None:
            self._slide.stop()
            self._slide = None
        for index, page in enumerate(self.pages):
            page.setGeometry(0, 0, self.width(), self.height())
            page.setVisible(index == self.current)

    def go(self, position: int) -> None:
        """Turn to the page at that place among those shown - sliding, from the side it lies on."""
        position = max(0, min(len(self.shown) - 1, position))
        index = self.shown[position]
        if index == self.current:
            return
        old, new = self.pages[self.current], self.pages[index]
        way = 1 if index > self.current else -1
        self.current = index
        self.changed.emit(position)
        if not theme.motion_on() or not self.isVisible():
            self._place()
            return
        if self._slide is not None:
            self._slide.stop()
        for page in self.pages:
            if page not in (old, new):
                page.hide()
        width = self.width()
        new.setGeometry(way * width, 0, width, self.height())
        new.show()
        slide = self._slide = QVariantAnimation(self)
        slide.setDuration(300)
        slide.setEasingCurve(QEasingCurve.OutCubic)
        slide.setStartValue(0.0)
        slide.setEndValue(1.0)
        slide.valueChanged.connect(lambda t: (old.move(round(-way * width * t), 0),
                                              new.move(round(way * width * (1 - t)), 0)))
        slide.finished.connect(self._place)
        slide.start()


class _Dots(QWidget):
    """Which page is in sight: a dot for each, the one in sight a pink capsule. Clicked, a dot turns
    to its page."""
    chosen = Signal(int)
    GAP = 12

    def __init__(self, count: int):
        super().__init__()
        self.count, self.current = count, 0
        self.setFixedSize(INNER, 10)
        self.setCursor(Qt.PointingHandCursor)

    def set_current(self, index: int) -> None:
        self.current = index
        self.update()

    def set_count(self, count: int) -> None:
        self.count = count
        self.current = min(self.current, count - 1)
        self.setVisible(count > 1)
        self.update()

    def _x(self, index: int) -> float:
        return self.width() / 2 + (index - (self.count - 1) / 2) * self.GAP

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            x = event.position().x()
            self.chosen.emit(min(range(self.count), key=lambda i: abs(self._x(i) - x)))

    def paintEvent(self, event):
        c = theme.colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        middle = self.height() / 2
        for index in range(self.count):
            if index == self.current:
                painter.setPen(QPen(c.edge, 1))
                painter.setBrush(QColor(theme.ACCENT))
                painter.drawRoundedRect(QRectF(self._x(index) - 6, middle - 3, 12, 6), 3, 3)
            else:
                dot = QColor(c.dim)
                dot.setAlphaF(0.55)
                painter.setPen(Qt.NoPen)
                painter.setBrush(dot)
                painter.drawEllipse(QPointF(self._x(index), middle), 2.5, 2.5)
        painter.end()


class EdgePanel(QWidget):
    open_app = Signal(str)
    open_hanami = Signal()
    open_pin = Signal(int)              # what is pinned, by its place on the page
    add_pins = Signal()                 # the plus after them: to Settings, to pin something
    mic_clicked = Signal()
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
        self._photo_cropped: QPixmap | None = None
        self._photo_key = None
        self._resting_since: float | None = None
        self._left_at: float | None = None
        self._sliding: QPropertyAnimation | None = None
        self._leaving = False
        self.stats_source = None        # what samples the PC's stats (stats.Sampler.take), once a second
        self._wheel, self._wheel_at = 0, 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 8)
        layout.setSpacing(8)
        self.handle = _Handle()
        self.handle.dragged.connect(self._drag_to)
        self.handle.dropped.connect(self._dropped)
        layout.addWidget(self.handle, 0, Qt.AlignHCenter)
        layout.addSpacing(-4)
        self.pages = _Pages()
        apps_page = QWidget()
        apps = QVBoxLayout(apps_page)
        apps.setContentsMargins(0, 0, 0, 0)
        apps.setSpacing(4)
        self.hanami = _AppButton('Hanami', icons.render_app_icon(ICON), False)
        self.hanami.clicked.connect(lambda _: self._chose(self.open_hanami.emit))
        apps.addWidget(self.hanami, 0, Qt.AlignHCenter)
        self._apps = QVBoxLayout()
        self._apps.setSpacing(4)
        apps.addLayout(self._apps)
        apps.addStretch(1)
        self.pages.add(apps_page)
        pins_page = QWidget()
        self._pins = QGridLayout(pins_page)
        self._pins.setContentsMargins(0, 0, 0, 0)
        self._pins.setHorizontalSpacing(4)
        self._pins.setVerticalSpacing(4)
        self._pins.setAlignment(Qt.AlignTop)
        self.pages.add(pins_page)
        stats_page = QWidget()
        stats = QVBoxLayout(stats_page)
        stats.setContentsMargins(0, 4, 0, 0)
        stats.setSpacing(10)
        self.stat_rows = {key: _Stat(name, bar) for key, name, bar in (
            ('cpu', 'CPU', True), ('cpu_temp', 'CPU temp', False), ('ram', 'RAM', True), ('gpu', 'GPU', True),
            ('vram', 'VRAM', True), ('gpu_temp', 'GPU temp', False))}
        for row in self.stat_rows.values():
            stats.addWidget(row)
        stats.addStretch(1)
        self.pages.add(stats_page)
        self.pages.changed.connect(self._page_turned)
        layout.addWidget(self.pages)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addStretch(1)
        self.sound = SoundToggle()
        self.sound.setFixedSize(INNER - MicButton.SIZE - 6, MicButton.SIZE)
        self.sound.chosen.connect(self.output_clicked)
        row.addWidget(self.sound)
        self.mic = MicButton()
        self.mic.clicked.connect(self.mic_clicked)
        row.addWidget(self.mic)
        row.addStretch(1)
        layout.addLayout(row)
        self.dots = _Dots(len(PAGES))             # at the very bottom: which page is in sight
        self.dots.chosen.connect(self.pages.go)
        layout.addWidget(self.dots, 0, Qt.AlignHCenter)
        self.buttons: dict[str, _AppButton] = {}
        self.pin_buttons: list[QWidget] = []
        self._stats = QTimer(self)
        self._stats.setInterval(STATS_EVERY)
        self._stats.timeout.connect(self._sample)

        self._watch = QTimer(self)
        self._watch.setInterval(WATCH_MS)
        self._watch.timeout.connect(self._look)
        self.tab = _EdgeTab()
        self.tab.clicked.connect(self._tab_clicked)
        self.tab.dragged.connect(self._tab_dragged)
        self.tab.dropped.connect(self._tab_dropped)
        self._tab_looked = 0.0
        self._tab_dragging = False
        self._hushed = False            # a game, or anything full screen, in front: nothing watched

    # ------------------------------------------------------------------ what it holds

    def show_apps(self, apps: list[tuple[str, QPixmap, bool]]) -> None:
        """The apps on this PC: (name, icon, running)."""
        for button in self.buttons.values():
            self._apps.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.buttons = {}
        for name, icon, running in apps:
            button = _AppButton(name, icon, running)
            button.clicked.connect(lambda n: self._chose(lambda: self.open_app.emit(n)))
            self.buttons[name] = button
            self._apps.addWidget(button, 0, Qt.AlignHCenter)
        self.pages.refit()
        self.adjustSize()

    def show_pins(self, pins: list[tuple[str, QPixmap]]) -> None:
        """What is pinned: (name, icon), two by two - then a plus, while there is room for more."""
        for button in self.pin_buttons:
            self._pins.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.pin_buttons = []
        for index, (name, icon) in enumerate(pins[:PINS_MOST]):
            button = _AppButton(name, icon, False, size=PIN_ICON, width=PIN_TILE)
            button.clicked.connect(lambda _, i=index: self._chose(lambda: self.open_pin.emit(i)))
            self.pin_buttons.append(button)
        if len(pins) < PINS_MOST:
            more = _AddButton()
            more.clicked.connect(lambda: self._chose(self.add_pins.emit))
            self.pin_buttons.append(more)
        for index, button in enumerate(self.pin_buttons):
            self._pins.addWidget(button, index // 2, index % 2)
        self.pages.refit()
        self.adjustSize()

    def show_mic(self, muted: bool | None) -> None:
        """The microphone: muted or not - None with none plugged in."""
        self.mic.show_muted(muted)

    def show_stats(self, stats) -> None:
        """A sample of the PC's stats (stats.Stats); the graphics card's only with NVIDIA's driver."""
        gb = 1024 ** 3
        rows = self.stat_rows
        rows['cpu'].set_value('…' if stats.cpu is None else f'{stats.cpu:.0f}%',
                              None if stats.cpu is None else stats.cpu / 100)
        rows['cpu_temp'].setVisible(stats.cpu_temp is not None)       # only with Hanami Sensors installed
        if stats.cpu_temp is not None:
            rows['cpu_temp'].set_value(f'{stats.cpu_temp:.0f}°C')
        used, total = stats.ram
        rows['ram'].set_value(f'{used / gb:.1f}/{total / gb:.0f} GB', used / total if total else 0.0)
        card = stats.gpu is not None or stats.vram is not None or stats.gpu_temp is not None
        for key in ('gpu', 'vram', 'gpu_temp'):
            rows[key].setVisible(card)
        if stats.gpu is not None:
            rows['gpu'].set_value(f'{stats.gpu:.0f}%', stats.gpu / 100)
        if stats.vram is not None and stats.vram[1]:
            rows['vram'].set_value(f'{stats.vram[0] / gb:.1f}/{stats.vram[1] / gb:.0f} GB', stats.vram[0] / stats.vram[1])
        if stats.gpu_temp is not None:
            rows['gpu_temp'].set_value(f'{stats.gpu_temp}°C')

    # ------------------------------------------------------------------ its pages

    def set_pages(self, names: list[str]) -> None:
        """Which pages it has (of PAGES), as chosen in Settings - always in PAGES' order. With just
        one, there are no dots."""
        self.pages.show_only([index for index, name in enumerate(PAGES) if name in names])
        self.dots.set_count(len(self.pages.shown))
        self.dots.set_current(self.pages.position)
        self._watch_stats()
        self.adjustSize()

    def wheelEvent(self, event):
        """The scroll wheel turns the pages - a notch a page, down to the next; a touchpad's
        scrolling, once it adds up to a notch."""
        delta = event.angleDelta().y() or event.angleDelta().x()
        now = time.monotonic()
        if now - self._wheel_at > 0.4:
            self._wheel = 0
        self._wheel_at = now
        self._wheel += delta
        if abs(self._wheel) >= 120:
            self.pages.go(self.pages.position + (1 if self._wheel < 0 else -1))
            self._wheel = 0
        event.accept()

    def _page_turned(self, index: int) -> None:
        self.dots.set_current(index)
        self._watch_stats()

    def _watch_stats(self) -> None:
        """Sample the PC's stats once a second - only while their page is in sight."""
        wanted = (self.isVisible() and not self._leaving and PAGES[self.pages.current] == 'stats'
                  and self.stats_source is not None)
        if wanted and not self._stats.isActive():
            self._sample()
            self._stats.start()
        elif not wanted:
            self._stats.stop()

    def _sample(self) -> None:
        try:
            self.show_stats(self.stats_source())
        except Exception:                   # noqa: BLE001 - a sample that fails leaves the last one
            pass

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._watch_stats)

    def hideEvent(self, event):
        self._stats.stop()
        super().hideEvent(event)

    def _chose(self, then) -> None:
        then()
        self.slide_away()

    # ------------------------------------------------------------------ the edge

    def set_tab(self, length: int, thickness: int, opacity: int) -> None:
        """The tab's look (_EdgeTab.set_look), shown at once where it is."""
        self.tab.set_look(length, thickness, opacity)
        if self.edge and not self._tab_dragging:
            self._show_tab()

    def set_edge(self, edge: str | None) -> None:
        """Watch that edge of the screen ('left' or 'right'), or none."""
        self.edge = edge if edge in EDGES else None
        self._resting_since = None
        self._tab_looked = 0.0
        if self.edge:
            self.tab.edge = self.edge
            self._show_tab()
            self._watch.start()
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

    def _hush(self) -> bool:
        """Whether a game, or anything full screen, is in front - and if that changed, the pointer
        no longer watched (only, now and then, whether it is still in front), or watched again."""
        quiet = self.quiet()
        if quiet != self._hushed:
            self._hushed = quiet
            self._resting_since = None
            self._watch.setInterval(QUIET_EVERY if quiet else WATCH_MS)
            if quiet:
                self.tab.hide()
                self.slide_away()
        return quiet

    def _show_tab(self) -> None:
        """The tab where the panel is - unless the panel is out, or something full screen is in front."""
        home = home_screen(self.edge) if self.edge else None
        if self._hush() or home is None or self.isVisible():
            self.tab.hide()
            return
        x = home.right() + 1 - self.tab.width() if self.edge == 'right' else home.left()
        place = QPoint(x, self._middle(home, self.tab.height()) - self.tab.height() // 2)
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
        length = self.tab.height()
        top = max(home.top() + MARGIN, min(middle - length // 2, home.bottom() + 1 - MARGIN - length))
        self.tab.move(self.tab.x(), top)

    def _tab_dropped(self) -> None:
        self._tab_dragging = False
        home = home_screen(self.edge) if self.edge else None
        if home is None:
            return
        self.place = max(0.0, min(1.0, (self.tab.y() + self.tab.height() / 2 - home.top()) / home.height()))
        self.moved.emit(self.place)

    def _look(self) -> None:
        now = time.monotonic()
        if self._hushed:                        # a game in front: only whether it has gone
            self._show_tab()
            return
        if not self._tab_dragging and now - self._tab_looked >= TAB_EVERY:
            self._tab_looked = now
            self._show_tab()
            if self._hushed:
                return
        point = pointer()
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
        """Where along the edge resting brings it out: beside where the panel comes out, and
        around the tab - a fifth of the screen's height at least, so it is easy to hit."""
        height = self._height(screen)
        top = self._top(screen, height)
        tab = self._middle(screen, self.tab.height())
        reach = max(self.tab.height() + 40, screen.height() // 5) / 2
        return round(min(top, tab - reach)), round(max(top + height, tab + reach))

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
        self._stats.stop()
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
        rect = QRectF(self.rect())
        radius = theme.LIQUID_RADIUS if theme.look() == 'liquid' and theme.glass_on() else theme.GLASS_RADIUS
        theme.paint_glass(painter, rect, radius)
        photo = self._cropped_photo()
        if photo is not None:
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)
            painter.setClipPath(path)
            painter.setOpacity(theme.BACKDROP_OPACITY)      # as faint as the main windows' backdrops
            painter.drawPixmap(0, 0, photo)
        painter.end()

    def _cropped_photo(self) -> QPixmap | None:
        """The photo, cropped to fill the panel - made again only when the panel's size changes."""
        if self._photo.isNull():
            return None
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr)
        if self._photo_key != key:
            size = QSize(round(self.width() * dpr), round(self.height() * dpr))
            scaled = self._photo.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            cropped = scaled.copy((scaled.width() - size.width()) // 2, (scaled.height() - size.height()) // 2,
                                  size.width(), size.height())
            cropped.setDevicePixelRatio(dpr)
            self._photo_cropped, self._photo_key = cropped, key
        return self._photo_cropped
