"""Hanami's window: every suite app, whether it's here and running, and the
buttons to install, start, update or quit it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QProgressBar,
                               QPushButton, QToolButton, QVBoxLayout, QWidget)

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
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        self.icon = QLabel()
        self.icon.setFixedSize(44, 44)
        layout.addWidget(self.icon, 0, Qt.AlignVCenter)   # centred on the card's name, words and buttons (the user's wish)
        # The gaps the eye sees (Keytap\.dev\spacing\BRIEF.md), 16 between the name
        # and what the app does and between that and the buttons (the user's wish: the same), 16
        # padding all round. The buttons sit at the foot, so a row of cards has them on one line.
        text = QVBoxLayout()
        text.setSpacing(0)
        heading = QHBoxLayout()
        heading.setSpacing(8)
        name = _serif(app.name, 13)
        heading.addWidget(name, 0, Qt.AlignTop)
        self.version = _label('', theme.TYPE['caption'], role='dim')
        # Centred on the name's capitals (the user's wish), not on its baseline: both boxes are their
        # ink, the name's from the top of its capitals
        cap = QFontMetricsF(name.font()).capHeight()
        self.version.setContentsMargins(0, max(0, round((cap - QFontMetricsF(self.version.font()).capHeight()) / 2)), 0, 0)
        heading.addWidget(self.version, 0, Qt.AlignTop)
        heading.addStretch(1)
        corner = QHBoxLayout()                      # the dot right by the ⋯, which its own padding parts it from
        corner.setSpacing(0)
        self.dot = _Dot()
        self.dot.setFixedHeight(round(cap))          # as tall as the name's capitals, so centred on them
        corner.addWidget(self.dot, 0, Qt.AlignTop)
        self.more = QToolButton()
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
        text.addSpacing(16)
        about = _label(app.description, theme.TYPE['small'], role='dim')
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
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.open = QPushButton('Open')             # pink only as Install: Open and Start are routine
        self.open.clicked.connect(self._primary)
        self.update = QPushButton('Update')
        self.update.setProperty('role', 'primary')
        self.update.clicked.connect(lambda: self.install_clicked.emit(app.name))
        self.quit = QPushButton('Quit')
        self.quit.clicked.connect(lambda: self.quit_clicked.emit(app.name))
        self.cancel = QPushButton('Cancel')
        self.cancel.clicked.connect(lambda: self.cancel_clicked.emit(app.name))
        for button in (self.open, self.update, self.quit, self.cancel):
            button.setCursor(Qt.PointingHandCursor)
            buttons.addWidget(button)
        buttons.addStretch(1)
        text.addSpacing(16)
        text.addLayout(buttons)
        layout.addLayout(text, 1)
        self._exe = None
        self._state = CardState()
        self._shown = None              # the state last shown, and the colours it was shown in

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
        image = win32.exe_icon(exe, round(44 * ratio)) if key else None
        if image is not None:
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(ratio)
        else:
            pixmap = placeholder_icon(self.app.name, 44)
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
        rebuild_menu = self._shown is None or self._shown[0].installed != s.installed
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
        self.open.setText('Install' if s.exe is None else 'Open' if s.running
                          else 'Starting…' if s.starting else 'Start')
        primary = 'primary' if s.exe is None else ''
        if self.open.property('role') != primary:
            self.open.setProperty('role', primary)
            self.open.style().unpolish(self.open)
            self.open.style().polish(self.open)
        self.open.setEnabled(not s.starting)
        self.open.setVisible(not busy)
        self.update.setText(f'Update to {s.latest}')
        self.update.setVisible(s.update and not busy)
        self.quit.setVisible(s.in_tray and not busy)
        self.cancel.setVisible(busy and s.busy in ('download', 'unpack', 'quit'))
        self.more.setVisible(not busy)

        if not rebuild_menu:
            return
        self.menu.clear()
        self.menu.addAction('Release notes', lambda: self.page_clicked.emit(self.app.name))
        self.menu.addAction('Find it on this PC…', lambda: self.locate_clicked.emit(self.app.name))
        if s.installed:
            self.menu.addSeparator()
            self.menu.addAction(f'Uninstall {self.app.name}', lambda: self.uninstall_clicked.emit(self.app.name))


class LauncherWindow(QWidget):
    open_app = Signal(str)
    quit_app = Signal(str)
    install_app = Signal(str)
    cancel_install = Signal(str)
    uninstall_app = Signal(str)
    show_page = Signal(str)
    update_hanami = Signal()
    exe_chosen = Signal(str, str)
    settings_clicked = Signal()
    output_clicked = Signal(str)        # 'speakers' or 'headphones' 

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Hanami')
        self.setWindowIcon(icons.app_icon())
        self.setMinimumWidth(700)
        self.setObjectName('launcher')
        theme.frost(self, backdrop=theme.BACKDROP)
        theme.closes_on_escape(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        top = QHBoxLayout()
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
        layout.addLayout(grid)
        layout.addStretch(1)

        self.foot = _label('', theme.TYPE['caption'], role='dim')
        self.foot.setTextFormat(Qt.RichText)
        self.foot.linkActivated.connect(lambda link: self.update_hanami.emit() if link == 'update'
                                        else self.show_page.emit('Hanami'))
        layout.addWidget(self.foot)
        theme.restyle(self, self._style)
        self.show_hanami('')

    def _settings_icon(self) -> None:
        self.settings.setIcon(suiteicons.icon('gear', theme.colors().text, 18))
        self.settings.setIconSize(QSize(18, 18))

    def show_hanami(self, newer: str, updating: str = '', can_update: bool = False, waiting: bool = False) -> None:
        """The footer: Hanami's version, and a newer one if there is one - to update to here (or,
        run from source, to see on GitHub) - or the one being put in."""
        words = f'Hanami {__version__}  ·  Closing this window keeps Hanami in the tray.'
        link = f'style="color:{theme.ink()}; text-decoration:none"'
        if updating and waiting:              # put in by itself, waiting for Hanami to be out of use
            words += f'  ·  <a href="update" {link}>Hanami {updating} is ready - restart to update</a>'
        elif updating:
            words += f'  ·  Updating to Hanami {updating}…'
        elif newer and can_update:
            words += f'  ·  <a href="update" {link}>Hanami {newer} is out - update</a>'
        elif newer:
            words += f'  ·  <a href="hanami" {link}>Hanami {newer} is out - get it</a>'
        self.foot.setText(words)

    def _style(self) -> str:
        c = theme.colors()
        return theme.card_style() + theme.panel_css('QFrame#card', 12) + f"""
            QWidget#launcher {{ background: {theme.css(c.card)}; }}
            QToolButton#settingsButton {{ color: {c.text.name()}; padding: 0px; }}
        """

    def _locate(self, name: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f'Where is {name}?', str(Path.home() / 'Documents'),
                                              'Programs (*.exe)')
        if path:
            self.exe_chosen.emit(name, path)
