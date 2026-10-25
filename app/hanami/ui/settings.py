"""Hanami's settings: starting with Windows, the suite's appearance (light or dark, its glass,
its animations), keeping quiet for games, the sound-output hotkey, updates, and about Hanami.

The appearance is the whole suite's: what is chosen here is kept for every suite app
(suitetheme.set_mode, set_look, set_motion), and each one running takes it within seconds.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (QColor, QFont, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout,
                               QHBoxLayout, QKeySequenceEdit, QLabel, QPushButton, QSlider, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import __version__
from ..catalog import SUITE
from . import icons, suitetheme, theme

SOURCE = 'https://github.com/blossqt/hanami'


def glyph_font(point_size: float) -> QFont:
    """Windows 11's icon font (Windows 10's, if that is all there is)."""
    f = QFont('Segoe Fluent Icons')
    if not f.exactMatch():
        f = QFont('Segoe MDL2 Assets')
    f.setPointSizeF(point_size)
    return f


def _label(text: str, size: float = 9.5, weight=QFont.Normal, role: str = '', wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setFont(theme.font(size, weight))
    if role:
        label.setProperty('role', role)
    label.setWordWrap(wrap)
    return label


def _section(title: str) -> tuple[QFrame, QVBoxLayout]:
    """A panel on a page, under its own heading."""
    frame = QFrame()
    frame.setObjectName('section')
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 14, 18, 16)
    layout.setSpacing(8)
    layout.addWidget(_label(title, 10.5, QFont.DemiBold))
    return frame, layout


def _switch(text: str, about: str, on: bool) -> tuple[QWidget, QCheckBox]:
    """A setting: a check box (a switch, in the liquid look), and a line about it below."""
    box = QCheckBox(text)
    box.setChecked(on)
    box.setCursor(Qt.PointingHandCursor)
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(1)
    layout.addWidget(box)
    if about:
        line = _label(about, 8.5, role='dim', wrap=True)
        line.setObjectName('about')
        _indent(line)
        layout.addWidget(line)
    return holder, box


def _indent(line: QLabel) -> None:
    """A line about a setting starts under its words, past the box (or switch) beside them."""
    liquid = theme.look() == 'liquid' and theme.glass_on()
    line.setContentsMargins((theme.SuiteStyle.SWITCH[0] if liquid else theme.SuiteStyle.SIZE) + 8, 0, 0, 0)


class _Nav(QWidget):
    """The pages down the left: a pill slides to the one chosen - springing into place, and
    stretching as it goes, in the liquid look."""

    chosen = Signal(int)
    ROW = 40

    def __init__(self, items: list[tuple[str, str]]):
        super().__init__()
        self._items = items
        self._current = 0
        self._hover = -1
        self._at = 0.0                  # where the pill is, in rows
        self._moving = 0.0              # how far through a move it is, for its stretch
        self._slide = None
        self.setFixedWidth(196)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(196, self.ROW * len(self._items) + 16)

    def current(self) -> int:
        return self._current

    def choose(self, index: int) -> None:
        if not 0 <= index < len(self._items) or index == self._current:
            return
        start = self._at
        self._current = index
        self.chosen.emit(index)
        if self._slide is not None:
            self._slide.stop()
        if not theme.motion_on():
            self._at = float(index)
            self.update()
            return
        slide = self._slide = QVariantAnimation(self)
        liquid = theme.look() == 'liquid' and theme.glass_on()
        curve = QEasingCurve(QEasingCurve.OutBack if liquid else QEasingCurve.OutCubic)
        if liquid:
            curve.setOvershoot(1.1)
        slide.setEasingCurve(curve)
        slide.setDuration(360 if liquid else 220)
        slide.setStartValue(start)
        slide.setEndValue(float(index))

        def step(value):
            self._at = float(value)
            span = abs(index - start) or 1
            self._moving = min(1.0, max(0.0, abs(self._at - start) / span))
            self.update()

        def done():
            self._moving = 0.0
            self.update()
        slide.valueChanged.connect(step)
        slide.finished.connect(done)
        slide.start()

    def _row_at(self, y: float) -> int:
        index = int((y - 8) // self.ROW)
        return index if 0 <= index < len(self._items) else -1

    def mousePressEvent(self, event):
        index = self._row_at(event.position().y())
        if index >= 0:
            self.choose(index)

    def mouseMoveEvent(self, event):
        index = self._row_at(event.position().y())
        if index != self._hover:
            self._hover = index
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Down, Qt.Key_Right):
            self.choose(self._current + 1)
        elif event.key() in (Qt.Key_Up, Qt.Key_Left):
            self.choose(self._current - 1)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        c = theme.colors()
        dark = theme.is_dark()
        liquid = theme.look() == 'liquid' and theme.glass_on()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        width = self.width() - 16
        if 0 <= self._hover != self._current:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 14) if dark else QColor(0, 0, 0, 10))
            p.drawRoundedRect(QRectF(8, 8 + self._hover * self.ROW + 2, width, self.ROW - 4), 8, 8)
        stretch = 6 * math.sin(math.pi * self._moving) if liquid else 0.0
        pill = QRectF(8, 8 + self._at * self.ROW + 2 - stretch / 2, width, self.ROW - 4 + stretch)
        if liquid:
            round_ = pill.height() / 2
            body = QLinearGradient(pill.topLeft(), pill.bottomLeft())
            body.setColorAt(0, QColor(255, 255, 255, 52 if dark else 235))
            body.setColorAt(1, QColor(255, 255, 255, 18 if dark else 140))
            p.setPen(Qt.NoPen)
            p.setBrush(body)
            p.drawRoundedRect(pill, round_, round_)
            suitetheme._edge_light(p, pill.adjusted(0.5, 0.5, -0.5, -0.5), round_, 120, 150 if dark else 255, 1.1)
            if not dark:
                p.setPen(QPen(QColor(0, 0, 0, 22), 1))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(pill, round_, round_)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(c.chip)
            p.drawRoundedRect(pill, 8, 8)
            bar = QRectF(pill.left() + 1, pill.center().y() - 8, 3, 16)
            p.setBrush(QColor(theme.ink()))
            p.drawRoundedRect(bar, 1.5, 1.5)
        for index, (mark, title) in enumerate(self._items):
            row = QRectF(8, 8 + index * self.ROW, width, self.ROW)
            selected = index == self._current
            p.setPen(QColor(theme.ink()) if selected else c.dim)
            p.setFont(glyph_font(11))
            p.drawText(QRectF(row.left() + 14, row.top(), 24, row.height()), Qt.AlignCenter, mark)
            p.setPen(c.text)
            p.setFont(theme.font(9.5, QFont.DemiBold if selected else QFont.Normal))
            p.drawText(QRectF(row.left() + 46, row.top(), row.width() - 50, row.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, title)
        if self.hasFocus() and self._current >= 0:
            p.setPen(QPen(QColor(theme.ink()), 1, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(pill.adjusted(-2, -2, 2, 2), 10, 10)
        p.end()


class _LookTile(QAbstractButton):
    """One of the suite's looks, as a picture of it - a pane of its glass over bright shapes and
    lines of text - with its name below; the chosen one ringed in pink."""

    def __init__(self, look: str, title: str):
        super().__init__()
        self.look = look
        self.title = title
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(232, 174)
        self._picture = None
        self._picture_key = None

    def sizeHint(self) -> QSize:
        return QSize(250, 180)

    def _scene(self, width: int, height: int, dpr: float) -> QPixmap:
        """What is behind the pane: bright shapes and lines of text, with room around."""
        pixmap = QPixmap(round(width * dpr), round(height * dpr))
        pixmap.setDevicePixelRatio(dpr)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        sky = QLinearGradient(0, 0, width, height)
        sky.setColorAt(0, QColor('#ffd6e3'))
        sky.setColorAt(0.5, QColor('#7cb6f0'))
        sky.setColorAt(1, QColor('#2f5fc4'))
        p.fillRect(QRectF(0, 0, width, height), sky)
        p.setPen(Qt.NoPen)
        for x, y, r, color in ((0.2, 0.75, 0.32, '#4fd1b5'), (0.78, 0.25, 0.26, '#ffb3c7'), (0.55, 0.62, 0.16, '#fff3a6')):
            p.setBrush(QColor(color))
            p.drawEllipse(QPointF(width * x, height * y), height * r, height * r)
        p.setBrush(QColor(20, 30, 60, 170))
        for i in range(6):
            y = 14 + i * height / 6.2
            p.drawRoundedRect(QRectF(12, y, width * (0.5 + 0.35 * ((i * 37) % 10) / 10), 5), 2.5, 2.5)
        p.end()
        return pixmap

    def _render(self, rect: QRectF) -> QPixmap:
        dpr = self.devicePixelRatioF()
        width, height = round(rect.width()), round(rect.height())
        margin = suitetheme._MARGIN
        scene = self._scene(width + 2 * margin, height + 2 * margin, dpr)
        picture = QPixmap(round(width * dpr), round(height * dpr))
        picture.setDevicePixelRatio(dpr)
        picture.fill(Qt.transparent)
        p = QPainter(picture)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        frame = QPainterPath()
        frame.addRoundedRect(QRectF(0, 0, width, height), 12, 12)
        p.setClipPath(frame)
        p.drawPixmap(QRectF(0, 0, width, height), scene,
                     QRectF(margin * dpr, margin * dpr, width * dpr, height * dpr))
        pane = QRectF(width * 0.17, height * 0.2, width * 0.66, height * 0.6)
        spec = dict(suitetheme._LENSES[self.look])
        shot = suitetheme._soften(scene, spec['blur'])
        lens = suitetheme._lens(shot, margin + pane.x(), margin + pane.y(), round(pane.width()), round(pane.height()), spec)
        radius = theme.LIQUID_RADIUS if self.look == 'liquid' else 10
        shape = QPainterPath()
        shape.addRoundedRect(pane, radius, radius)
        p.setClipPath(shape)
        p.drawPixmap(QRectF(pane.topLeft(), QPointF(pane.x() + pane.width(), pane.y() + pane.height())), lens,
                     QRectF(lens.rect()))
        p.setClipping(False)
        dark = theme.is_dark()
        if self.look == 'liquid':
            tint = QLinearGradient(pane.topLeft(), pane.bottomLeft())
            tint.setColorAt(0, QColor(62, 58, 70, 70) if dark else QColor(255, 255, 255, 60))
            tint.setColorAt(1, QColor(12, 10, 16, 70) if dark else QColor(178, 178, 184, 60))
            p.fillPath(shape, tint)
        else:
            p.fillPath(shape, QColor(18, 16, 24, 118) if dark else QColor(255, 255, 255, 128))
        suitetheme._edge_light(p, pane, radius, 120, 230, 1.2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 230) if dark else QColor(30, 30, 40, 200))
        p.drawRoundedRect(QRectF(pane.x() + 14, pane.y() + 14, pane.width() * 0.45, 6), 3, 3)
        p.setBrush(QColor(255, 255, 255, 140) if dark else QColor(30, 30, 40, 110))
        p.drawRoundedRect(QRectF(pane.x() + 14, pane.y() + 26, pane.width() * 0.62, 4), 2, 2)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(pane.x() + 14, pane.bottom() - 26, 44, 14), 7 if self.look == 'liquid' else 4,
                          7 if self.look == 'liquid' else 4)
        p.end()
        return picture

    def paintEvent(self, event):
        c = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        preview = QRectF(r.x(), r.y(), r.width(), r.height() - 28)
        key = (round(preview.width()), round(preview.height()), self.devicePixelRatioF(), theme.is_dark())
        if key != self._picture_key:
            self._picture = self._render(preview)
            self._picture_key = key
        if not self.isEnabled():
            p.setOpacity(0.5)
        p.drawPixmap(preview.topLeft(), self._picture)
        if self.isChecked() or self.underMouse():
            p.setPen(QPen(QColor(theme.ink()), 2.2 if self.isChecked() else 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(preview.adjusted(-1.5, -1.5, 1.5, 1.5), 13.5, 13.5)
        if self.isChecked():
            badge = QRectF(preview.right() - 28, preview.top() + 8, 20, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawEllipse(badge)
            p.setPen(QPen(QColor(theme.ON_ACCENT), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            tick = QPainterPath(QPointF(badge.x() + 5.5, badge.y() + 10.5))
            tick.lineTo(badge.x() + 8.8, badge.y() + 13.6)
            tick.lineTo(badge.x() + 14.6, badge.y() + 7)
            p.setBrush(Qt.NoBrush)
            p.drawPath(tick)
        p.setPen(c.text)
        p.setFont(theme.font(10, QFont.DemiBold))
        p.drawText(QRectF(r.x() + 2, preview.bottom() + 6, r.width(), 20), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        p.end()


class SettingsWindow(QWidget):
    startup_changed = Signal(bool, list)
    updates_changed = Signal(bool, bool, bool)      # look by itself, tell me, install by itself
    sound_changed = Signal(bool, str)               # the hotkey on, the hotkey
    output_chosen = Signal(str, str, str)           # 'speakers' or 'headphones', the output's id ('' for none), its name
    panel_changed = Signal(str)                     # the edge the panel slides out at: 'right', 'left' or '' (off)
    tab_changed = Signal(int, int, int)             # the panel's tab: its length and thickness (px), opacity at rest (%)
    check_now = Signal()
    show_page = Signal(str)
    open_url = Signal(str)

    PAGES = [('', 'General'), ('', 'Appearance'), ('', 'Games'), ('', 'Sound'), ('', 'Updates'),
             ('', 'About')]

    def __init__(self, start_with: list[str], starts_with_windows: bool, updates: tuple[bool, bool, bool],
                 sound: tuple[bool, str] = (True, ''), panel_edge: str = 'right',
                 tab: tuple[int, int, int] | None = None):
        super().__init__()
        self.setWindowTitle('Hanami settings')
        self.setWindowIcon(icons.app_icon())
        self.setObjectName('settings')
        self.setMinimumSize(800, 560)
        theme.frost(self, backdrop=theme.BACKDROP)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 16, 20, 16)
        outer.setSpacing(12)
        side = QVBoxLayout()
        side.setSpacing(10)
        top = QHBoxLayout()
        top.setContentsMargins(14, 0, 0, 0)
        top.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(icons.render_app_icon(28))
        top.addWidget(logo)
        top.addWidget(_label('Settings', 13, QFont.DemiBold), 1)
        side.addLayout(top)
        self.nav = _Nav(self.PAGES)
        side.addWidget(self.nav)
        side.addStretch(1)
        outer.addLayout(side)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._general(start_with, starts_with_windows, panel_edge, tab))
        self.pages.addWidget(self._appearance())
        self.pages.addWidget(self._games())
        self.pages.addWidget(self._sound(*sound))
        self.pages.addWidget(self._updates(*updates))
        self.pages.addWidget(self._about())
        self.nav.chosen.connect(self.pages.setCurrentIndex)
        outer.addWidget(self.pages, 1)
        theme.restyle(self, self._style)
        theme.on_restyle(self._appearance_changed)

    def open_page(self, name: str) -> None:
        for index, (_, title) in enumerate(self.PAGES):
            if title.lower() == name.lower():
                self.nav.choose(index)

    # ------------------------------------------------------------------ pages

    @staticmethod
    def _page(title: str, about: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)
        layout.addWidget(_label(title, 17, QFont.DemiBold))
        if about:
            layout.addWidget(_label(about, 9, role='dim', wrap=True))
        return page, layout

    def _general(self, start_with: list[str], starts_with_windows: bool, panel_edge: str = 'right',
                 tab: tuple[int, int, int] | None = None) -> QWidget:
        from .panel import TAB_LIMITS, TAB_LOOK          # (the panel's sound switch is drawn from here)
        page, layout = self._page('General', '')
        frame, box = _section('Starting up')
        holder, self.startup = _switch('Start Hanami when I sign in to Windows',
                                       'It starts in the tray, without opening its window.',
                                       starts_with_windows)
        box.addWidget(holder)
        box.addWidget(_label('Start with Hanami, in the background:', 9, role='dim'))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)
        self.start_with: dict[str, QCheckBox] = {}
        for index, app in enumerate(SUITE):
            check = QCheckBox(app.name)
            check.setChecked(app.name in start_with)
            check.setCursor(Qt.PointingHandCursor)
            check.toggled.connect(self._startup_edited)
            self.start_with[app.name] = check
            grid.addWidget(check, index // 2, index % 2)
        grid.setColumnStretch(2, 1)
        box.addLayout(grid)
        self.startup.toggled.connect(self._startup_edited)
        layout.addWidget(frame)
        frame, box = _section('Edge panel')
        holder, self.panel_on = _switch('Slide out a panel at the edge of the screen',
                                        'A little tab at the edge shows where it is: rest the pointer on it, or click '
                                        'it. Drag the tab, or the panel’s handle, to move it. It holds the suite’s apps '
                                        'and the sound switch, and keeps away from games and anything full screen.',
                                        bool(panel_edge))
        self.panel_on.toggled.connect(self._panel_edited)
        box.addWidget(holder)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(_label('Edge:', 9.5))
        self.panel_edges = QButtonGroup(self)
        self.edge_buttons: dict[str, QPushButton] = {}
        for name, title in (('left', 'Left'), ('right', 'Right')):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setChecked((panel_edge or 'right') == name)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(self._panel_edited)
            self.panel_edges.addButton(button)
            self.edge_buttons[name] = button
            row.addWidget(button)
        row.addStretch(1)
        box.addLayout(row)
        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self.tab_sliders: dict[str, QSlider] = {}
        for index, (name, title, unit, value, (least, most)) in enumerate(zip(
                ('length', 'thickness', 'opacity'), ('Tab length', 'Tab thickness', 'Tab opacity'),
                (' px', ' px', '%'), tab or TAB_LOOK, TAB_LIMITS)):
            slider = QSlider(Qt.Horizontal)
            slider.setRange(least, most)
            slider.setValue(value)
            slider.setCursor(Qt.PointingHandCursor)
            slider.setAccessibleName(title)
            shown = _label(f'{value}{unit}', 9.5, role='dim')
            shown.setMinimumWidth(48)
            slider.valueChanged.connect(lambda v, shown=shown, unit=unit: (shown.setText(f'{v}{unit}'),
                                                                           self._tab_edited()))
            grid.addWidget(_label(title, 9.5), index, 0)
            grid.addWidget(slider, index, 1)
            grid.addWidget(shown, index, 2)
            self.tab_sliders[name] = slider
        grid.setColumnStretch(1, 1)
        box.addLayout(grid)
        self._panel_edited(emit=False)
        layout.addWidget(frame)
        frame, box = _section('The tray')
        box.addWidget(_label('Closing Hanami’s window keeps it in the tray, as the blossom. Its menu holds each running '
                             'app’s own menu, and Quit Hanami.', 9, role='dim', wrap=True))
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def _appearance(self) -> QWidget:
        page, layout = self._page('Appearance', 'For every suite app: Keytap, Dropshift, Grabbit and Homework Hub '
                                                'follow what you choose here within a few seconds.')
        frame, box = _section('Light or dark')
        row = QHBoxLayout()
        row.setSpacing(6)
        self.modes = QButtonGroup(self)
        self.mode_buttons: dict[str, QPushButton] = {}
        for name, title in theme.MODES.items():
            button = QPushButton(title)
            button.setCheckable(True)
            button.setChecked(theme.mode() == name)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _, n=name: theme.set_mode(n))
            self.modes.addButton(button)
            self.mode_buttons[name] = button
            row.addWidget(button)
        row.addStretch(1)
        box.addLayout(row)
        layout.addWidget(frame)

        frame, box = _section('Glass')
        tiles = QHBoxLayout()
        tiles.setSpacing(16)
        self.looks = QButtonGroup(self)
        self.look_tiles: dict[str, _LookTile] = {}
        for name, title in theme.LOOKS.items():
            tile = _LookTile(name, title)
            tile.setChecked(theme.look() == name)
            tile.setEnabled(theme.glass_on())
            tile.clicked.connect(lambda _, n=name: theme.set_look(n))
            self.looks.addButton(tile)
            self.look_tiles[name] = tile
            tiles.addWidget(tile)
        tiles.addStretch(1)
        box.addLayout(tiles)
        if not theme.glass_on():
            box.addWidget(_label('Glass needs Windows 11 with transparency effects on (Settings > Personalisation > '
                                 'Colours).', 8.5, role='dim', wrap=True))
        layout.addWidget(frame)

        frame, box = _section('Motion')
        holder, self.motion = _switch('Animations', 'Also off when Windows’ animation effects are off.',
                                      theme.motion_chosen())
        self.motion.toggled.connect(theme.set_motion)
        box.addWidget(holder)
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def _games(self) -> QWidget:
        page, layout = self._page('Games', '')
        frame, box = _section('While a full-screen game is in front')
        holder, self.game_quiet = _switch('Keep the suite quiet', 'Notifications wait until you leave the game, and '
                                          'the glass stops updating.', theme.game_quiet_chosen())
        self.game_quiet.toggled.connect(self._game_edited)
        box.addWidget(holder)
        box.addWidget(_label('Grabbit’s downloads:', 9, role='dim'))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.game_downloads = QButtonGroup(self)
        self.download_buttons: dict[str, QPushButton] = {}
        for name, title in theme.GAME_DOWNLOADS.items():
            button = QPushButton(title)
            button.setCheckable(True)
            button.setChecked(theme.game_downloads() == name)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _, n=name: theme.set_game_downloads(n))
            self.game_downloads.addButton(button)
            self.download_buttons[name] = button
            row.addWidget(button)
        row.addStretch(1)
        box.addLayout(row)
        box.addWidget(_label('Slowed down, they take at most 1 MB/s down and 64 KB/s up.', 8.5, role='dim', wrap=True))
        box.addSpacing(4)
        box.addWidget(_label('A game counts when Windows knows it as one, as Game Bar does, and its window fills the '
                             'screen.', 8.5, role='dim', wrap=True))
        self._game_edited(theme.game_quiet_chosen(), save=False)
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def _sound(self, on: bool, hotkey: str) -> QWidget:
        page, layout = self._page('Sound', '')
        frame, box = _section('Sound output')
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.output_choices: dict[str, QComboBox] = {}
        for row, (which, title) in enumerate((('speakers', 'Speakers:'), ('headphones', 'Headphones:'))):
            combo = QComboBox()
            combo.setMinimumWidth(320)
            combo.setCursor(Qt.PointingHandCursor)
            combo.currentIndexChanged.connect(lambda _, w=which: self._output_edited(w))
            self.output_choices[which] = combo
            grid.addWidget(_label(title, 9.5), row, 0)
            grid.addWidget(combo, row, 1)
        grid.setColumnStretch(2, 1)
        box.addLayout(grid)
        box.addWidget(_label('The switch at the top of Hanami’s window goes between these two.', 8.5, role='dim',
                             wrap=True))
        box.addSpacing(6)
        holder, self.sound_on = _switch('Switch between them with a hotkey', 'A pop-up names the output it went '
                                        'to.', on)
        self.sound_on.toggled.connect(self._sound_edited)
        box.addWidget(holder)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(_label('Hotkey:', 9.5))
        self.sound_key = QKeySequenceEdit(QKeySequence(hotkey))
        self.sound_key.setMaximumSequenceLength(1)
        self.sound_key.setClearButtonEnabled(True)
        self.sound_key.setFixedWidth(200)
        self.sound_key.editingFinished.connect(self._sound_edited)
        row.addWidget(self.sound_key)
        row.addStretch(1)
        box.addLayout(row)
        self.sound_problem = _label('', 9, role='error', wrap=True)
        self.sound_problem.hide()
        box.addWidget(self.sound_problem)
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def show_outputs(self, outputs: list, chosen: dict) -> None:
        """The sound outputs plugged in now, with the ones chosen as speakers and headphones
        ({'speakers': (id, name) or None, ...}) - one chosen but not plugged in is still there."""
        for which, combo in self.output_choices.items():
            picked = chosen.get(which)
            combo.blockSignals(True)
            combo.clear()
            combo.addItem('None', ('', ''))
            for output in outputs:
                combo.addItem(output.name, (output.id, output.name))
            if picked and picked[0] not in {output.id for output in outputs}:
                combo.addItem(f'{picked[1]} (not connected)', tuple(picked))
            index = next((i for i in range(combo.count()) if picked and combo.itemData(i)[0] == picked[0]), 0)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def show_sound_problem(self, problem: str) -> None:
        self.sound_problem.setText(problem)
        self.sound_problem.setVisible(bool(problem))

    def _updates(self, check: bool, notify: bool, auto: bool) -> QWidget:
        page, layout = self._page('Updates', 'Hanami installs and updates the suite’s apps from their releases on '
                                             'GitHub, checking each one’s signature first.')
        frame, box = _section('Updates')
        holder, self.check = _switch('Look for updates by itself', 'Twice a day, and when you open Hanami.', check)
        box.addWidget(holder)
        holder, self.notify = _switch('Tell me when one is out', '', notify)
        box.addWidget(holder)
        holder, self.auto = _switch('Install updates by itself', 'For the apps Hanami installed, while they aren’t '
                                    'running; one you’re using is updated once you quit it.', auto)
        box.addWidget(holder)
        for switch in (self.check, self.notify, self.auto):
            switch.toggled.connect(self._updates_edited)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.check_button = QPushButton('Look now')
        self.check_button.setCursor(Qt.PointingHandCursor)
        self.check_button.clicked.connect(self.check_now)
        row.addWidget(self.check_button)
        self.checked = _label('', 9, role='dim')
        row.addWidget(self.checked, 1)
        box.addSpacing(4)
        box.addLayout(row)
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    def _about(self) -> QWidget:
        page, layout = self._page('About', '')
        frame, box = _section('Hanami')
        row = QHBoxLayout()
        row.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(icons.render_app_icon(64))
        row.addWidget(logo, 0, Qt.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(4)
        words.addWidget(_label(f'Hanami {__version__}', 13, QFont.DemiBold))
        words.addWidget(_label('The suite’s launcher. It keeps one tray icon for every suite app, and installs and '
                               'updates them from their signed releases.', 9, role='dim', wrap=True))
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        notes = QPushButton('Release notes')
        notes.clicked.connect(lambda: self.show_page.emit('Hanami'))
        source = QPushButton('Source code')
        source.clicked.connect(lambda: self.open_url.emit(SOURCE))
        for button in (notes, source):
            button.setCursor(Qt.PointingHandCursor)
            buttons.addWidget(button)
        buttons.addStretch(1)
        words.addSpacing(6)
        words.addLayout(buttons)
        row.addLayout(words, 1)
        box.addLayout(row)
        layout.addWidget(frame)
        frame, box = _section('Thanks')
        self.credit = _label('', 9, role='dim', wrap=True)
        self.credit.setTextFormat(Qt.RichText)
        self.credit.setOpenExternalLinks(True)
        self._show_credit()
        box.addWidget(self.credit)
        box.addWidget(_label('MIT licence · made by blossqt', 8.5, role='dim'))
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ changes

    def _startup_edited(self, *_, emit: bool = True) -> None:
        if emit:
            self.startup_changed.emit(self.startup.isChecked(),
                                      [name for name, check in self.start_with.items() if check.isChecked()])

    def _game_edited(self, on: bool, save: bool = True) -> None:
        if save:
            theme.set_game_quiet(on)
        for button in self.download_buttons.values():
            button.setEnabled(on)

    def _panel_edited(self, *_, emit: bool = True) -> None:
        on = self.panel_on.isChecked()
        for button in [*self.edge_buttons.values(), *self.tab_sliders.values()]:
            button.setEnabled(on)
        edge = next((name for name, button in self.edge_buttons.items() if button.isChecked()), 'right')
        if emit:
            self.panel_changed.emit(edge if on else '')

    def _tab_edited(self) -> None:
        s = self.tab_sliders
        self.tab_changed.emit(s['length'].value(), s['thickness'].value(), s['opacity'].value())

    def _sound_edited(self, *_) -> None:
        keys = self.sound_key.keySequence()
        hotkey = keys.toString(QKeySequence.PortableText) if not keys.isEmpty() else ''
        self.sound_changed.emit(self.sound_on.isChecked(), hotkey)

    def _output_edited(self, which: str) -> None:
        combo = self.output_choices[which]
        if combo.signalsBlocked():
            return
        output_id, name = combo.currentData() or ('', '')
        self.output_chosen.emit(which, output_id, name)

    def _updates_edited(self, *_) -> None:
        self.updates_changed.emit(self.check.isChecked(), self.notify.isChecked(), self.auto.isChecked())

    def _show_credit(self) -> None:
        link = f'style="color:{theme.ink()}; text-decoration:none"'
        self.credit.setText(f'The blossom behind this window is a photo by <a href="https://unsplash.com/photos/'
                            f'pkpqoBp11Jc" {link}>Mi Min</a> on Unsplash, and the one behind the edge panel by '
                            f'<a href="https://unsplash.com/photos/j3TrGxN_rCM" {link}>Yan Liu</a>.')

    def show_checked(self, text: str, checking: bool) -> None:
        self.checked.setText(text)
        self.check_button.setEnabled(not checking)

    def _appearance_changed(self) -> None:
        """The look, light or dark, or the animations changed (here, or in another copy): the
        choices show it."""
        try:
            for name, button in self.mode_buttons.items():
                button.setChecked(theme.mode() == name)
            for name, tile in self.look_tiles.items():
                tile.setChecked(theme.look() == name)
                tile.update()
            if self.motion.isChecked() != theme.motion_chosen():
                self.motion.blockSignals(True)
                self.motion.setChecked(theme.motion_chosen())
                self.motion.blockSignals(False)
            for name, button in self.download_buttons.items():
                button.setChecked(theme.game_downloads() == name)
            for line in self.findChildren(QLabel, 'about'):
                _indent(line)
            self._show_credit()
            self.nav.update()
        except RuntimeError:                                # the window has gone
            pass

    def _style(self) -> str:
        c = theme.colors()
        return theme.card_style() + theme.panel_css('QFrame#section', 12) + f"""
            QWidget#settings {{ background: {theme.css(c.card)}; }}
            QStackedWidget, QStackedWidget > QWidget {{ background: transparent; }}
            QSlider {{ min-height: 22px; background: transparent; }}
            QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {theme.css(c.border)}; }}
            QSlider::sub-page:horizontal {{ height: 4px; border-radius: 2px; background: {theme.ACCENT}; }}
            QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0; border-radius: 8px;
                                          background: {theme.ACCENT}; border: 1px solid {theme.ink()}; }}
            QSlider::handle:horizontal:hover {{ background: {theme.ACCENT_HOVER}; }}
            QSlider::sub-page:horizontal:disabled, QSlider::handle:horizontal:disabled {{
                background: {theme.css(c.border)}; border-color: {theme.css(c.border)}; }}
        """
