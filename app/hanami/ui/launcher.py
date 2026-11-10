"""Hanami's window: every suite app, whether it's here and running, and the
buttons to install, start, update or quit it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPen, QPixmap, QRegion
from PySide6.QtWidgets import (QFileDialog, QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel,
                               QMenu, QProgressBar, QStyle, QStyleOption, QStyleOptionFrame,
                               QPushButton, QScrollArea, QSizePolicy, QSpacerItem, QToolButton, QVBoxLayout,
                               QWidget)

from .. import __version__, win32
from ..catalog import SUITE
from . import icons, suiteicons, theme
from .sound import SoundToggle


def _serif(text: str, size: float) -> QLabel:
    """A name or title, in the suite's Geist Serif (its box its ink: theme.Label)."""
    label = theme.Label(text)
    label.setFont(theme.serif(size))
    return label


def _label(text: str, size: float, weight=QFont.Normal, role: str = '') -> QLabel:
    label = theme.Label(text)
    label.setFont(theme.font(size, weight))
    if role:
        label.setProperty('role', role)
    return label


def placeholder_icon(name: str, size: int) -> QPixmap:
    """An app not on this PC yet: the suite's tile with its initial, until its own icon is here."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(icons.APP_ICON_COLOR))
    corner = size * 42 / 192
    painter.drawRoundedRect(QRectF(0, 0, size, size), corner, corner)
    painter.setPen(QColor(icons.APP_ICON_MARK))
    painter.setFont(theme.font(size * 0.3, QFont.DemiBold))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, name[:1])
    painter.end()
    return pixmap


@dataclass
class CardState:
    exe: Path | None = None         # where the app is, if it is on this PC
    running: bool = False
    in_tray: bool = False           # running, its menu in Hanami's tray icon
    version: str = ''               # of the copy on this PC, when known
    installed: bool = False         # installed by Hanami, so Hanami can update or remove it
    latest: str = ''                # the newest release, when known
    update: bool = False            # latest is newer than the installed copy
    problem: str = ''               # why the last check or install didn't work
    busy: str = ''                  # what an install under way is doing
    done: int = 0
    total: int = 0
    starting: bool = False          # started a moment ago, and not up yet


# How much of a card shows, roomiest first: the window takes the first that fits it, so nothing is
# ever cut off. FULL: what the app does and its buttons under its name. BRIEF: without what it does.
# LINE: one line, its buttons beside its name. ICONS: the same, with the buttons as icons.
FULL, BRIEF, LINE, ICONS = range(4)
TIERS = (FULL, BRIEF, LINE, ICONS)
_ROOMY_PAD, _SLIM_PAD = 16, 12          # a card's padding
_ROOMY_MARGIN, _SLIM_MARGIN = 24, 16    # the window's
_ROOMY_GAP, _SLIM_GAP = 16, 8           # between cards
_ICON = 44
_NO_LIMIT = 16777215                    # Qt's QWIDGETSIZE_MAX, which PySide doesn't export
_ICON_BUTTON = 30                       # a button's width, as an icon
_BUTTON_PADDING = 40                    # a button's width, past its words
_TRAY_WORDS = 'Closing this window keeps Hanami in the tray.'

_BUSY = {'download': 'Downloading', 'unpack': 'Unpacking', 'check': 'Checking it starts',
         'place': 'Putting it in place', 'quit': 'Waiting for it to quit', 'remove': 'Removing it'}



class _Dot(QWidget):
    """Whether the app runs, at the card's top right by its ⋯ (the user's wish, 2026-11-02, in
    place of a "Running · in the tray" line): green while it runs, a ring while it doesn't, nothing
    while it isn't on this PC. Its tooltip says it in words."""

    SIZE = 8

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.SIZE, self.SIZE)
        self.state: str | None = None

    def set(self, state: str | None, words: str) -> None:
        self.setToolTip(words)
        self.setVisible(state is not None)
        if state != self.state:
            self.state = state
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, (self.height() - self.SIZE) / 2, self.SIZE, self.SIZE)     # centred in its height
        if self.state == 'running':
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#2f9e44'))
        else:
            p.setPen(QPen(QColor(theme.colors().dim), 1.6))
            p.setBrush(Qt.NoBrush)
        p.drawEllipse(r.adjusted(1, 1, -1, -1))         # 6 px, ring or not
        p.end()


class AppCard(QFrame):
    open_clicked = Signal(str)
    quit_clicked = Signal(str)
    install_clicked = Signal(str)
    cancel_clicked = Signal(str)
    uninstall_clicked = Signal(str)
    locate_clicked = Signal(str)
    page_clicked = Signal(str)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName('card')
        self._tier = FULL
        self._button_h = 30
        self._words: list[str] = []     # on the buttons in sight
        self._about_h = (-1, 0)         # (width, the height what it does takes there)
        self._menu_for = None
        self._shape = None              # what it shows, as far as its size and buttons go
        self.before_change = None       # called just before that changes: the window's morph
        layout = self.row = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        self.icon = QLabel()
        self.icon.setFixedSize(_ICON, _ICON)
        layout.addWidget(self.icon, 0, Qt.AlignTop)   # its top level with the top of the name's capitals (the user's wish)
        # The gaps the eye sees (Keytap\.dev\spacing\BRIEF.md), 16 between the name
        # and what the app does and between that and the buttons (the user's wish: the same), 16
        # padding all round. The buttons sit at the foot, so a row of cards has them on one line.
        text = self.column = QVBoxLayout()
        text.setSpacing(0)
        heading = self.heading = QHBoxLayout()
        heading.setSpacing(8)
        name = self.name = _serif(app.name, 13)
        heading.addWidget(name, 0, Qt.AlignTop)
        self.version = _label('', theme.TYPE['caption'], role='dim')
        # Centred on the name's capitals (the user's wish), not on its baseline: both boxes are their
        # ink, the name's from the top of its capitals
        cap = self._cap = QFontMetricsF(name.font()).capHeight()
        self._version_drop = max(0, round((cap - QFontMetricsF(self.version.font()).capHeight()) / 2))
        self.version.setContentsMargins(0, self._version_drop, 0, 0)
        heading.addWidget(self.version, 0, Qt.AlignTop)
        heading.addStretch(1)
        corner = QHBoxLayout()                      # the dot right by the ⋯, which its own padding parts it from
        corner.setSpacing(0)
        self.dot = _Dot()
        self.dot.setFixedHeight(round(cap))          # as tall as the name's capitals, so centred on them
        corner.addWidget(self.dot, 0, Qt.AlignTop)
        self.more = QToolButton()
        self.more.setObjectName('moreButton')
        self._more_icon()                           # Lucide's ellipsis, not a ⋯ character
        theme.on_restyle(self._more_icon)
        self.more.setPopupMode(QToolButton.InstantPopup)
        self.more.setCursor(Qt.PointingHandCursor)
        self.more.setToolTip('More')
        self.more.setFixedSize(28, round(cap))      # as tall as the name's capitals, centred on them;
                                                    # as narrow as its dots, so the running dot sits by them
        self.menu = QMenu(self.more)
        self.more.setMenu(self.menu)
        corner.addWidget(self.more, 0, Qt.AlignTop)
        heading.addLayout(corner)
        text.addLayout(heading)
        self.gap_name = QSpacerItem(0, 16, QSizePolicy.Minimum, QSizePolicy.Fixed)
        text.addItem(self.gap_name)
        about = self.about = _label(app.description, theme.TYPE['small'], role='dim')
        about.setWordWrap(True)
        text.addWidget(about)
        self.status = QWidget()                     # only while there is something to say: an install, a problem
        status = QVBoxLayout(self.status)
        status.setContentsMargins(0, 16, 0, 0)
        status.setSpacing(16)
        self.state = _label('', theme.TYPE['caption'])
        self.state.setWordWrap(True)
        status.addWidget(self.state)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        status.addWidget(self.progress)
        text.addWidget(self.status)
        text.addStretch(1)                          # spare height above the buttons, never under
        buttons = self.actions = QHBoxLayout()
        buttons.setSpacing(8)
        self.open = QPushButton('Open')             # pink only as Install: Open and Start are routine
        self.open.clicked.connect(self._primary)
        self.update_button = QPushButton('Update')
        self.update_button.setProperty('role', 'primary')
        self.update_button.clicked.connect(lambda: self.install_clicked.emit(app.name))
        self.quit = QPushButton('Quit')
        self.quit.clicked.connect(lambda: self.quit_clicked.emit(app.name))
        self.cancel = QPushButton('Cancel')
        self.cancel.clicked.connect(lambda: self.cancel_clicked.emit(app.name))
        for button in (self.open, self.update_button, self.quit, self.cancel):
            button.setCursor(Qt.PointingHandCursor)
            buttons.addWidget(button)
        self.push = QSpacerItem(0, 0, QSizePolicy.Expanding, QSizePolicy.Minimum)     # to the left, under the name
        buttons.addItem(self.push)
        self.gap_actions = QSpacerItem(0, 16, QSizePolicy.Minimum, QSizePolicy.Fixed)
        text.addItem(self.gap_actions)
        text.addLayout(buttons)
        layout.addLayout(text, 1)
        self._exe = None
        self._state = CardState()
        self._shown = None              # the state last shown, and the colours it was shown in

    # ---------------------------------------------------------------- how much of it shows
    def _slim_button_h(self) -> int:
        if self._tier != ICONS:         # as an icon it has no words to be measured by
            self.quit.ensurePolished()
            self._button_h = self.quit.sizeHint().height()
        return self._button_h

    def slim_height(self) -> int:
        return self._border() + 2 * _SLIM_PAD + self._slim_button_h()

    def _border(self) -> int:
        self.ensurePolished()
        return self.width() - self.contentsRect().width()

    def _status_height(self, width: int, gap: int) -> int:
        if not self.status.isVisibleTo(self):
            return 0
        layout = self.status.layout()
        total = layout.totalHeightForWidth(width) if layout.hasHeightForWidth() else layout.totalSizeHint().height()
        return total - layout.contentsMargins().top() + gap

    def _buttons_width(self, icons_only: bool) -> int:
        if not self._words:
            return 0
        metrics = self.open.fontMetrics()
        each = [_ICON_BUTTON if icons_only else metrics.horizontalAdvance(w) + _BUTTON_PADDING for w in self._words]
        return sum(each) + 8 * (len(each) - 1)

    def least_width(self, tier: int) -> int:
        """The narrowest this card reads at, showing that much."""
        self.name.ensurePolished()
        title = self.name.sizeHint().width()
        if tier != ICONS:
            title += 8 + self.version.sizeHint().width()
        corner = 8 + 8 + 28             # the dot and the ⋯, and what parts them from the name
        if tier <= BRIEF:
            return self._border() + 2 * _ROOMY_PAD + _ICON + 16 + max(title + corner, self._buttons_width(False))
        return (self._border() + 2 * _SLIM_PAD + self._slim_button_h() + 12 + title + 8
                + self._buttons_width(tier == ICONS) + corner)

    def height_for(self, tier: int, width: int) -> int:
        """How tall this card is, showing that much, at that width."""
        if tier >= LINE:
            inner = width - self._border() - 2 * _SLIM_PAD - self._slim_button_h() - 12
            return self.slim_height() + self._status_height(inner, 8)
        inner = width - self._border() - 2 * _ROOMY_PAD - _ICON - 16
        height = max(self.name.sizeHint().height(), round(self._cap)) + 16 + self._slim_button_h()
        height += self._status_height(inner, 16)
        if tier == FULL:
            if self._about_h[0] != inner:
                self._about_h = (inner, self.about.heightForWidth(inner))
            height += self._about_h[1] + 16
        return self._border() + 2 * _ROOMY_PAD + max(height, _ICON)

    def set_tier(self, tier: int) -> None:
        if tier == self._tier:
            return
        button_h = self._slim_button_h()    # before it may become an icon
        was_slim, slim = self._tier >= LINE, tier >= LINE
        was_icons, icons = self._tier == ICONS, tier == ICONS
        self._tier = tier
        if slim != was_slim:
            if slim:
                self.column.removeItem(self.actions)
                self.heading.insertLayout(3, self.actions)      # after the name, its version and the stretch
            else:
                self.heading.removeItem(self.actions)
                self.column.addLayout(self.actions)
            self.push.changeSize(0, 0, QSizePolicy.Fixed if slim else QSizePolicy.Expanding, QSizePolicy.Minimum)
            pad = _SLIM_PAD if slim else _ROOMY_PAD
            self.row.setContentsMargins(pad, pad, pad, pad)
            self.row.setSpacing(12 if slim else 16)
            self.gap_actions.changeSize(0, 0 if slim else 16, QSizePolicy.Minimum, QSizePolicy.Fixed)
            self.status.layout().setContentsMargins(0, 8 if slim else 16, 0, 0)
            # one line, the name's capitals level with the middle of the buttons
            row = button_h if slim else round(self._cap)
            drop = (button_h - round(self._cap)) // 2 if slim else 0
            self.name.setContentsMargins(0, drop, 0, 0)
            self.version.setContentsMargins(0, drop + self._version_drop, 0, 0)
            self.dot.setFixedHeight(row)
            self.more.setFixedSize(28, row)
            size = button_h if slim else _ICON
            self.icon.setFixedSize(size, size)
            self._exe = None                # drawn afresh at its new size
        self.about.setVisible(tier == FULL)
        self.version.setVisible(tier != ICONS)
        self.gap_name.changeSize(0, 16 if tier == FULL else 0, QSizePolicy.Minimum, QSizePolicy.Fixed)
        if icons != was_icons:
            for button in (self.open, self.update_button, self.quit, self.cancel):
                button.setProperty('slim', icons)
                button.style().unpolish(button)
                button.style().polish(button)
                if icons:
                    button.setFixedSize(_ICON_BUTTON, button_h)
                else:
                    button.setMinimumSize(0, 0)
                    button.setMaximumSize(_NO_LIMIT, _NO_LIMIT)
        self.layout().invalidate()
        self.column.invalidate()
        self._shown = None
        self.show_state(self._state)

    def _dress(self, button: QPushButton, words: str, mark: str, tip: str = '') -> None:
        """A button's words, or its icon where there is room for only that."""
        if self._tier == ICONS:
            ink = theme.ON_ACCENT if button.property('role') == 'primary' else theme.colors().text
            button.setText('')
            button.setIcon(suiteicons.icon(mark, ink, 16))
            button.setIconSize(QSize(16, 16))
            button.setToolTip(tip or words)
        else:
            button.setIcon(QIcon())
            button.setText(words)
            button.setToolTip(tip)

    def _primary(self) -> None:
        if self._state.exe is None:
            self.install_clicked.emit(self.app.name)
        else:
            self.open_clicked.emit(self.app.name)

    def _show_icon(self, exe: Path | None) -> None:
        """The app's own icon, read from its exe - again whenever the exe is rebuilt or updated."""
        try:
            key = (exe, exe.stat().st_mtime) if exe else None
        except OSError:
            key = None
        if key == self._exe and not self.icon.pixmap().isNull():
            return
        self._exe = key
        ratio = self.devicePixelRatioF()
        size = self.icon.width()
        image = win32.exe_icon(exe, round(size * ratio)) if key else None
        if image is not None:
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(ratio)
        else:
            pixmap = placeholder_icon(self.app.name, size)
        self.icon.setPixmap(pixmap)

    def _more_icon(self) -> None:
        try:
            # heavier than the set's stroke: its dots are the whole drawing, as big as the ⋯ was
            self.more.setIcon(suiteicons.icon('more', theme.colors().text, 20, 2.8))
            self.more.setIconSize(QSize(20, 20))
        except RuntimeError:                        # the card is gone
            pass

    def show_state(self, s: CardState) -> None:
        """The card as the app is now - unchanged, nothing is done (it is asked every 2 s, and
        through an install)."""
        shown = (s, theme.colors().dim.name(), theme.ink())
        if shown == self._shown:
            return
        busy = bool(s.busy)
        shape = (s.exe is None, s.running, s.starting, s.update and not busy, s.in_tray and not busy, busy,
                 bool(s.problem), bool(s.version))     # not an install's progress, which moves all along
        if self._shape is not None and shape != self._shape and self.before_change is not None:
            self.before_change()
        self._shape = shape
        rebuild_menu = self._menu_for != s.installed
        self._menu_for = s.installed
        self._shown = shown
        self._state = s
        self._show_icon(s.exe)
        self.version.setText(s.version or (s.latest if s.exe is None else ''))     # not here yet: the newest
        c = theme.colors()
        dim = c.dim.name()
        if s.busy:
            words = _BUSY.get(s.busy, s.busy) + '…'
            if s.busy == 'download' and s.total:
                words = f'Downloading {s.latest}…  {s.done / 1e6:.0f} of {s.total / 1e6:.0f} MB'
            line = f'<span style="color:{dim}">{words}</span>'
        else:                                       # running or not: the dot on the icon (the user's wish,
            line = ''                               # 2026-11-02); not installed or a new version: the buttons
        if s.problem and not s.busy:
            line += f'<span style="color:{c.error.name()}">{s.problem}</span>'
        self.state.setText(line)
        self.state.setVisible(bool(line))
        self.dot.set(None if s.exe is None else 'running' if s.running else 'stopped',
                     'Running, in the tray' if s.running and s.in_tray else 'Running' if s.running
                     else 'Not running')

        busy = bool(s.busy)
        self.progress.setVisible(busy)
        self.status.setVisible(bool(line) or busy)
        if busy:
            fraction = s.total > 0 and s.busy in ('download', 'unpack')
            self.progress.setRange(0, 1000 if fraction else 0)
            if fraction:
                self.progress.setValue(int(1000 * s.done / s.total))
        words = 'Install' if s.exe is None else 'Open' if s.running else 'Starting…' if s.starting else 'Start'
        primary = 'primary' if s.exe is None else ''
        if self.open.property('role') != primary:
            self.open.setProperty('role', primary)
            self.open.style().unpolish(self.open)
            self.open.style().polish(self.open)
        self._dress(self.open, words, 'download' if s.exe is None else 'external' if s.running else 'play')
        self.open.setEnabled(not s.starting)
        self.open.setVisible(not busy)
        # 'Update to 0.2.36' didn't fit beside Open and Quit on a laptop's narrower cards, and was cut
        # at both ends: the button says Update, and its tooltip which version
        self._dress(self.update_button, 'Update', 'refresh', f'Update to {s.latest}' if s.latest else '')
        self.update_button.setVisible(s.update and not busy)
        self._dress(self.quit, 'Quit', 'cross')
        self.quit.setVisible(s.in_tray and not busy)
        self._dress(self.cancel, 'Cancel', 'cross')
        self.cancel.setVisible(busy and s.busy in ('download', 'unpack', 'quit'))
        self._words = [w for w, on in ((words, not busy), ('Update', s.update and not busy), ('Quit', s.in_tray and not busy),
                                       ('Cancel', busy and s.busy in ('download', 'unpack', 'quit'))) if on]
        self.more.setVisible(not busy)

        if not rebuild_menu:
            return
        self.menu.clear()
        self.menu.addAction('Release notes', lambda: self.page_clicked.emit(self.app.name))
        self.menu.addAction('Find it on this PC…', lambda: self.locate_clicked.emit(self.app.name))
        if s.installed:
            self.menu.addSeparator()
            self.menu.addAction(f'Uninstall {self.app.name}', lambda: self.uninstall_clicked.emit(self.app.name))


class _Morph(QWidget):
    """The cards' change as one movement rather than a jump. Just before the window shows less or
    more of each card, rearranges them or a card's buttons change, what each card shows is pictured,
    and again once the change is laid out. Each card then travels from where it was to where it is:
    its own rounded background drawn by its own style at every size between, and what it showed
    fading into what it shows inside it. The cards themselves come back once it has arrived. Drawn
    over the window, letting the mouse through."""

    def __init__(self, window: QWidget, holder: QWidget, cards: dict, area: QScrollArea):
        super().__init__(window)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()
        self._window, self._holder, self._cards, self._area = window, holder, cards, area
        self._was: dict = {}            # card: (where it was in the window, its picture then)
        self._now: dict = {}            # card: its picture now
        self._t = 1.0
        self._run = None
        self._hidden = None
        self._pending = False

    def capture(self) -> None:
        """Picture the cards as they are, just before a change; the change plays once it is laid out."""
        if self._pending or not self._window.isVisible() or not theme.motion_on():
            return
        self.finish()
        self._was = {card: (self._where(card), self._contents(card)) for card in self._cards.values()
                     if card.isVisible()}
        if self._was:
            self._pending = True
            QTimer.singleShot(0, self._play)

    def _contents(self, card: QWidget) -> QPixmap:
        """What a card shows, without its background: drawn round its shape as that changes."""
        ratio = card.devicePixelRatioF()
        picture = QPixmap(card.size() * ratio)
        picture.setDevicePixelRatio(ratio)
        picture.fill(Qt.transparent)
        p = QPainter(picture)
        for part in card.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            if part.isVisible():
                part.render(p, part.pos(), QRegion(), QWidget.RenderFlag.DrawChildren)
        p.end()
        return picture

    @staticmethod
    def _background(p: QPainter, card: QWidget, shape: QRect) -> None:
        """The card's own background and edge, as its style sheet draws them, at this size."""
        option = QStyleOption()
        option.initFrom(card)
        option.rect = shape
        card.style().drawPrimitive(QStyle.PE_Widget, option, p, card)
        frame = QStyleOptionFrame()
        card.initStyleOption(frame)
        frame.rect = shape
        card.style().drawControl(QStyle.CE_ShapedFrame, frame, p, card)

    def _where(self, card: QWidget) -> QRectF:
        return QRectF(card.mapTo(self._window, QPoint(0, 0)), card.size())

    def _play(self) -> None:
        self._pending = False
        if not self._was or not self._window.isVisible():
            self._was = {}
            return
        self._now = {card: self._contents(card) for card in self._cards.values() if card.isVisible()}
        self._hidden = QGraphicsOpacityEffect(self._holder)     # the cards themselves, until it arrives
        self._hidden.setOpacity(0.0)
        self._holder.setGraphicsEffect(self._hidden)
        self.setGeometry(self._window.rect())
        self.raise_()
        self.show()
        run = self._run = QVariantAnimation(self)
        run.setDuration(theme.STEADY)
        run.setEasingCurve(QEasingCurve.OutCubic)
        run.setStartValue(0.0)
        run.setEndValue(1.0)
        run.valueChanged.connect(self._step)
        run.finished.connect(self.finish)
        theme.animate(run)

    def _step(self, value) -> None:
        self._t = float(value)
        self.update()

    def finish(self) -> None:
        """Straight to the end: the cards as they are now, nothing over them."""
        run, self._run = self._run, None
        if run is not None:
            try:
                run.finished.disconnect(self.finish)
            except (RuntimeError, TypeError):
                pass
            theme.stop_animation(run)
        if self._hidden is not None:
            if self._holder.graphicsEffect() is self._hidden:
                self._holder.setGraphicsEffect(None)
            self._hidden = None
        self._was, self._now = {}, {}
        self._t = 1.0
        self.hide()

    @staticmethod
    def _crop(p: QPainter, picture: QPixmap, shape: QRectF, size: QRectF) -> None:
        """A picture at its own size, never squashed, cut to the shape it travels as."""
        ratio = picture.devicePixelRatio()
        width, height = min(shape.width(), size.width()), min(shape.height(), size.height())
        p.drawPixmap(QRectF(shape.x(), shape.y(), width, height), picture, QRectF(0, 0, width * ratio, height * ratio))

    def paintEvent(self, event):
        if not self._was and not self._now:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        viewport = self._area.viewport()
        p.setClipRect(QRectF(viewport.mapTo(self._window, QPoint(0, 0)), viewport.size()))
        t = self._t
        for card in list(self._was) + [c for c in self._now if c not in self._was]:
            was, before = self._was.get(card, (None, None))
            now = self._where(card) if card.isVisible() and card in self._now else None   # live, as the window moves
            frm, to = was or now, now or was
            shape = QRect(round(frm.x() + (to.x() - frm.x()) * t), round(frm.y() + (to.y() - frm.y()) * t),
                          round(frm.width() + (to.width() - frm.width()) * t),
                          round(frm.height() + (to.height() - frm.height()) * t))
            # a card coming or going fades as a whole; one that stays keeps its background whole
            p.setOpacity(t if before is None else 1.0 - t if now is None else 1.0)
            self._background(p, card, shape)
            if before is not None:
                p.setOpacity(1.0 - t)
                self._crop(p, before, QRectF(shape), was)
            if now is not None:
                p.setOpacity(t)
                self._crop(p, self._now[card], QRectF(shape), now)
        p.end()


class _CardsArea(QScrollArea):
    """The cards, scrolled up and down only, and that only when a card has more to say than fits
    (an install's progress, in the smallest window): the window keeps them in sight by showing less
    of each. A pane of its own: straight in the window, their wrapped words gave it a least height
    for each width, and Qt trimmed every drag to fit it."""

    relaid = Signal()

    def __init__(self, cards: QWidget):
        super().__init__()
        self.setObjectName('cards')
        self.setWidget(cards)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cards.installEventFilter(self)

    def _bar(self) -> int:
        return self.verticalScrollBar().sizeHint().width()

    def sizeHint(self) -> QSize:
        return self.widget().sizeHint() + QSize(self._bar(), 0)     # opens with every card in sight

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)                          # the window's own least size sees to this

    def eventFilter(self, obj, event) -> bool:
        if obj is self.widget() and event.type() == QEvent.LayoutRequest:
            self.updateGeometry()
            self.relaid.emit()                      # a card's buttons or status changed
        return False


class LauncherWindow(QWidget):
    open_app = Signal(str)
    quit_app = Signal(str)
    install_app = Signal(str)
    cancel_install = Signal(str)
    uninstall_app = Signal(str)
    show_page = Signal(str)
    update_hanami = Signal()
    check_updates = Signal()
    exe_chosen = Signal(str, str)
    settings_clicked = Signal()
    output_clicked = Signal(str)        # 'speakers' or 'headphones' 

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Hanami')
        self.setWindowIcon(icons.app_icon())
        self.setObjectName('launcher')
        theme.frost(self, backdrop=theme.BACKDROP)
        theme.closes_on_escape(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_ROOMY_MARGIN, _ROOMY_MARGIN, _ROOMY_MARGIN, _ROOMY_MARGIN)
        layout.setSpacing(16)
        self._tier = FULL
        self._fitting = False
        self._foot = ('', '', '')       # the footer whole, as plain words, and without the line about the tray
        self._foot_args = ('', '', False, False)
        self._checking = self._current = False

        top = self.top = QHBoxLayout()
        top.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(icons.render_app_icon(40))
        top.addWidget(logo, 0, Qt.AlignVCenter)
        top.addWidget(_serif('Hanami', 21), 1, Qt.AlignVCenter)
        self.sound = SoundToggle()
        self.sound.chosen.connect(self.output_clicked)
        top.addWidget(self.sound, 0, Qt.AlignVCenter)
        self.settings = QToolButton()
        self.settings.setObjectName('settingsButton')
        self._settings_icon()
        theme.on_restyle(self._settings_icon)
        self.settings.setToolTip('Settings')
        self.settings.setCursor(Qt.PointingHandCursor)
        self.settings.setFixedSize(38, 38)
        self.settings.clicked.connect(self.settings_clicked)
        top.addWidget(self.settings, 0, Qt.AlignVCenter)
        layout.addLayout(top)

        holder = QWidget()
        holder.setObjectName('cards')
        stack = QVBoxLayout(holder)
        stack.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        grid.setSpacing(16)                         # as from the header to the cards: even
        self.cards: dict[str, AppCard] = {}
        for index, app in enumerate(SUITE):
            card = AppCard(app)
            card.open_clicked.connect(self.open_app)
            card.quit_clicked.connect(self.quit_app)
            card.install_clicked.connect(self.install_app)
            card.cancel_clicked.connect(self.cancel_install)
            card.uninstall_clicked.connect(self.uninstall_app)
            card.page_clicked.connect(self.show_page)
            card.locate_clicked.connect(self._locate)
            theme.light_up(card, 18)
            self.cards[app.name] = card
            grid.addWidget(card, index // 2, index % 2)
        for column in (0, 1):
            grid.setColumnStretch(column, 1)
        self.grid = grid
        self._arranged = [app.name for app in SUITE]
        stack.addLayout(grid)
        stack.addStretch(1)
        self.cards_area = _CardsArea(holder)
        self.cards_area.relaid.connect(self._fit)
        layout.addWidget(self.cards_area, 1)
        self.morph = _Morph(self, holder, self.cards, self.cards_area)
        for card in self.cards.values():
            card.before_change = self.morph.capture

        self.foot = _label('', theme.TYPE['caption'], role='dim')
        self.foot.setTextFormat(Qt.RichText)
        self.foot.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)     # the window may be narrower than its words
        self.foot.linkActivated.connect(self._foot_link)
        layout.addWidget(self.foot)
        theme.restyle(self, self._style)
        self.show_hanami('')

    def arrange(self, names: list[str]) -> None:
        """Only these apps' cards, two to a row in the suite's order, with no gap where one is left
        out (an app shown only once it is installed)."""
        if names == self._arranged:
            return
        self.morph.capture()
        self._arranged = list(names)
        for card in self.cards.values():
            self.grid.removeWidget(card)
        for index, name in enumerate(names):
            self.grid.addWidget(self.cards[name], index // 2, index % 2)
        for name, card in self.cards.items():
            card.setVisible(name in names)
        self._fit()

    # ---------------------------------------------------------------- showing less as it shrinks
    def _rows(self) -> list[list[AppCard]]:
        cards = [self.cards[name] for name in self._arranged]
        return [cards[i:i + 2] for i in range(0, len(cards), 2)]

    def _fit(self) -> None:
        """How much of each card shows: the most that keeps every card whole in this window. Worked
        out from the window's size alone, so what it chooses can't change what it would choose."""
        if self._fitting or not self.isVisible():
            return
        self._fitting = True
        try:
            rows = self._rows()
            cards = [card for row in rows for card in row]
            if not cards:
                return
            chrome = self.top.sizeHint().height() + self.foot.sizeHint().height() + 2 * 16
            self._hold_minimum(rows, cards, chrome)
            tier = ICONS
            for choice in TIERS:
                margin = _SLIM_MARGIN if choice >= LINE else _ROOMY_MARGIN
                gap = _SLIM_GAP if choice >= LINE else _ROOMY_GAP
                width = (self.width() - 2 * margin - gap) // 2
                room = self.height() - 2 * margin - chrome
                tall = sum(max(c.height_for(choice, width) for c in row) for row in rows) + gap * (len(rows) - 1)
                if tall <= room and all(c.least_width(choice) <= width for c in cards):
                    tier = choice
                    break
            self._show_tier(tier, cards)
            self._show_foot()
        finally:
            self._fitting = False

    def _hold_minimum(self, rows, cards, chrome: int) -> None:
        """The window goes no smaller than every card on one line, buttons as icons."""
        width = 2 * max(c.least_width(ICONS) for c in cards) + _SLIM_GAP + 2 * _SLIM_MARGIN
        height = (sum(max(c.slim_height() for c in row) for row in rows) + _SLIM_GAP * (len(rows) - 1)
                  + 2 * _SLIM_MARGIN + chrome)
        if (self.minimumWidth(), self.minimumHeight()) != (width, height):
            self.setMinimumSize(width, height)

    def _show_tier(self, tier: int, cards: list) -> None:
        if tier != self._tier:
            self.morph.capture()
        for card in self.cards.values():        # those out of sight too, ready for when they are shown
            card.set_tier(tier)
        if tier == self._tier:
            return
        self._tier = tier
        margin = _SLIM_MARGIN if tier >= LINE else _ROOMY_MARGIN
        self.layout().setContentsMargins(margin, margin, margin, margin)
        self.grid.setSpacing(_SLIM_GAP if tier >= LINE else _ROOMY_GAP)
        self.grid.invalidate()
        self.layout().activate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()
        if self.morph.isVisible():
            self.morph.setGeometry(self.rect())

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def _settings_icon(self) -> None:
        self.settings.setIcon(suiteicons.icon('gear', theme.colors().text, 18))
        self.settings.setIconSize(QSize(18, 18))

    def _foot_link(self, link: str) -> None:
        if link == 'update':
            self.update_hanami.emit()
        elif link == 'check':
            self.check_updates.emit()
        else:
            self.show_page.emit('Hanami')

    def show_checking(self, checking: bool, current: bool) -> None:
        """The footer's own word on looking for updates: under way, or nothing found just now."""
        if (checking, current) != (self._checking, self._current):
            self._checking, self._current = checking, current
            self.show_hanami(*self._foot_args)

    def show_hanami(self, newer: str, updating: str = '', can_update: bool = False, waiting: bool = False) -> None:
        """The footer: Hanami's version, and a newer one if there is one - to update to here (or,
        run from source, to see on GitHub) - or the one being put in, or else the way to look."""
        self._foot_args = (newer, updating, can_update, waiting)
        name = f'Hanami {__version__}'
        link = f'style="color:{theme.ink()}; text-decoration:none"'
        plain = note = ''
        if updating and waiting:              # put in by itself, waiting for Hanami to be out of use
            plain = f'Hanami {updating} is ready - restart to update'
            note = f'<a href="update" {link}>{plain}</a>'
        elif updating:
            plain = note = f'Updating to Hanami {updating}…'
        elif newer and can_update:
            plain = f'Hanami {newer} is out - update'
            note = f'<a href="update" {link}>{plain}</a>'
        elif newer:
            plain = f'Hanami {newer} is out - get it'
            note = f'<a href="hanami" {link}>{plain}</a>'
        elif self._checking:
            plain = note = 'Checking for updates…'
        elif self._current:
            plain = note = 'Everything is up to date'
        else:
            plain = 'Check for updates'
            note = f'<a href="check" {link}>{plain}</a>'
        apart = '  ·  '
        self._foot = (name + apart + _TRAY_WORDS + (apart + note if note else ''),
                      name + apart + _TRAY_WORDS + (apart + plain if plain else ''),
                      name + (apart + note if note else ''))
        self._show_foot()

    def _show_foot(self) -> None:
        """The footer, the line about the tray left out when the window is too narrow for it."""
        whole, plain, short = self._foot
        margin = _SLIM_MARGIN if self._tier >= LINE else _ROOMY_MARGIN
        words = whole if self.foot.fontMetrics().horizontalAdvance(plain) <= self.width() - 2 * margin else short
        if self.foot.text() != words:
            self.foot.setText(words)

    def _style(self) -> str:
        c = theme.colors()
        return theme.card_style() + theme.panel_css('QFrame#card', 12) + f"""
            QWidget#launcher {{ background: {theme.css(c.card)}; }}
            QScrollArea#cards, QScrollArea#cards > QWidget, QWidget#cards {{ background: transparent; }}
            QToolButton#settingsButton {{ color: {c.text.name()}; padding: 0px; }}
            QToolButton#moreButton, QToolButton#moreButton:hover {{ border: none; padding: 0px; }}
            QPushButton[slim="true"] {{ padding: 0px; }}
        """

    def _locate(self, name: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f'Where is {name}?', str(Path.home() / 'Documents'),
                                              'Programs (*.exe)')
        if path:
            self.exe_chosen.emit(name, path)
