"""Hanami's window: every suite app, whether it's here and running, and the
buttons to install, start, update or quit it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QFileInfo, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFileIconProvider, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from .. import __version__
from ..catalog import SUITE
from . import icons, theme


def _label(text: str, size: float, weight=QFont.Normal, role: str = '') -> QLabel:
    label = QLabel(text)
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
    in_tray: bool = False           # running and in the blossom
    version: str = ''               # of the copy on this PC, when known
    installed: bool = False         # installed by Hanami, so Hanami can update or remove it
    latest: str = ''                # the newest release, when known
    update: bool = False            # latest is newer than the installed copy
    problem: str = ''               # why the last check or install didn't work
    busy: str = ''                  # what an install under way is doing
    done: int = 0
    total: int = 0


_BUSY = {'download': 'Downloading', 'unpack': 'Unpacking', 'check': 'Checking it starts',
         'place': 'Putting it in place', 'quit': 'Waiting for it to quit', 'remove': 'Removing it'}


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
        layout.setContentsMargins(16, 14, 12, 14)
        layout.setSpacing(14)
        self.icon = QLabel()
        self.icon.setFixedSize(44, 44)
        layout.addWidget(self.icon, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        heading = QHBoxLayout()
        heading.setSpacing(8)
        heading.addWidget(_label(app.name, 11.5, QFont.DemiBold))
        self.version = _label('', 8.5, role='dim')
        heading.addWidget(self.version, 0, Qt.AlignBaseline)
        heading.addStretch(1)
        self.more = QToolButton()
        self.more.setText('⋯')
        self.more.setFont(theme.font(13, QFont.Bold))
        self.more.setPopupMode(QToolButton.InstantPopup)
        self.more.setCursor(Qt.PointingHandCursor)
        self.more.setToolTip('More')
        self.menu = QMenu(self.more)
        self.more.setMenu(self.menu)
        heading.addWidget(self.more, 0, Qt.AlignTop)
        text.addLayout(heading)
        about = _label(app.description, 8.75, role='dim')
        about.setWordWrap(True)
        text.addWidget(about)
        self.state = _label('', 8.5)
        self.state.setWordWrap(True)
        text.addWidget(self.state)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        text.addWidget(self.progress)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.open = QPushButton('Open')
        self.open.setProperty('role', 'primary')
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
        text.addSpacing(4)
        text.addLayout(buttons)
        layout.addLayout(text, 1)
        self._exe = None
        self._state = CardState()

    def _primary(self) -> None:
        if self._state.exe is None:
            self.install_clicked.emit(self.app.name)
        else:
            self.open_clicked.emit(self.app.name)

    def show_state(self, s: CardState) -> None:
        self._state = s
        if s.exe != self._exe or self.icon.pixmap().isNull():
            self._exe = s.exe
            pixmap = (QFileIconProvider().icon(QFileInfo(str(s.exe))).pixmap(44, 44) if s.exe else None)
            if pixmap is None or pixmap.isNull():
                pixmap = placeholder_icon(self.app.name, 44)
            self.icon.setPixmap(pixmap)
        self.version.setText(s.version)
        c = theme.colors()
        dim, rose = c.dim.name(), theme.ACCENT if theme.is_dark() else theme.ON_ACCENT
        if s.busy:
            words = _BUSY.get(s.busy, s.busy) + '…'
            if s.busy == 'download' and s.total:
                words = f'Downloading {s.latest}…  {s.done / 1e6:.0f} of {s.total / 1e6:.0f} MB'
            line = f'<span style="color:{dim}">{words}</span>'
        elif s.exe is None:
            available = f' · {s.latest} available' if s.latest else ''
            line = f'<span style="color:{dim}">○</span>&nbsp; Not installed{available}'
        elif s.running:
            line = '<span style="color:#2f9e44">●</span>&nbsp; Running' + (' · in the blossom' if s.in_tray else '')
        else:
            line = f'<span style="color:{dim}">○</span>&nbsp; Not running'
        if s.update and not s.busy:
            line += f' · <span style="color:{rose}">{s.latest} is out</span>'
        if s.problem and not s.busy:
            line += f'<br><span style="color:{c.error.name()}">{s.problem}</span>'
        self.state.setText(line)

        busy = bool(s.busy)
        self.progress.setVisible(busy)
        if busy:
            fraction = s.total > 0 and s.busy in ('download', 'unpack')
            self.progress.setRange(0, 1000 if fraction else 0)
            if fraction:
                self.progress.setValue(int(1000 * s.done / s.total))
        self.open.setText('Install' if s.exe is None else 'Open' if s.running else 'Start')
        self.open.setVisible(not busy)
        self.update.setText(f'Update to {s.latest}')
        self.update.setVisible(s.update and not busy)
        self.quit.setVisible(s.in_tray and not busy)
        self.cancel.setVisible(busy and s.busy in ('download', 'unpack', 'quit'))
        self.more.setVisible(not busy)

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
    exe_chosen = Signal(str, str)
    startup_changed = Signal(bool, list)

    def __init__(self, start_with: list[str], starts_with_windows: bool):
        super().__init__()
        self.setWindowTitle('Hanami')
        self.setWindowIcon(icons.app_icon())
        self.setMinimumWidth(700)
        self.setObjectName('launcher')
        self._apply_style()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(icons.render_app_icon(40))
        top.addWidget(logo, 0, Qt.AlignVCenter)
        top.addWidget(_label('Hanami', 17, QFont.DemiBold), 1, Qt.AlignVCenter)
        layout.addLayout(top)

        grid = QGridLayout()
        grid.setSpacing(12)
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
            self.cards[app.name] = card
            grid.addWidget(card, index // 2, index % 2)
        for column in (0, 1):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)

        bottom = QVBoxLayout()
        bottom.setSpacing(8)
        self.startup = QCheckBox('Start Hanami when I sign in to Windows, and with it:')
        self.startup.setChecked(starts_with_windows)
        bottom.addWidget(self.startup)
        row = QHBoxLayout()
        row.setContentsMargins(28, 0, 0, 0)
        row.setSpacing(18)
        self.start_with: dict[str, QCheckBox] = {}
        for app in SUITE:
            box = QCheckBox(app.name)
            box.setChecked(app.name in start_with)
            box.toggled.connect(self._startup_edited)
            self.start_with[app.name] = box
            row.addWidget(box)
        row.addStretch(1)
        bottom.addLayout(row)
        self.startup.toggled.connect(self._startup_edited)
        layout.addLayout(bottom)
        self._startup_edited()

        self.foot = _label('', 8, role='dim')
        self.foot.setTextFormat(Qt.RichText)
        self.foot.linkActivated.connect(lambda _: self.show_page.emit('Hanami'))
        layout.addWidget(self.foot)
        self.show_hanami('')

    def show_hanami(self, newer: str) -> None:
        """The footer: Hanami's version, and a newer one if there is one."""
        words = f'Hanami {__version__}  ·  Closing this window keeps Hanami in the tray.'
        if newer:
            colour = theme.ACCENT if theme.is_dark() else theme.ON_ACCENT
            words += (f'  ·  <a href="hanami" style="color:{colour}; text-decoration:none">'
                      f'Hanami {newer} is out - get it</a>')
        self.foot.setText(words)

    def _apply_style(self) -> None:
        c = theme.colors()
        self.setStyleSheet(theme.card_style() + f"""
            QWidget#launcher {{ background: {c.card.name()}; }}
            QFrame#card {{ background: {c.tile.name()}; border: 1px solid {c.border.name(QColor.HexArgb)};
                           border-radius: 12px; }}
        """)

    def _startup_edited(self, *_) -> None:
        on = self.startup.isChecked()
        for box in self.start_with.values():
            box.setEnabled(on)
        self.startup_changed.emit(on, [name for name, box in self.start_with.items() if box.isChecked()])

    def _locate(self, name: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f'Where is {name}?', str(Path.home() / 'Documents'),
                                              'Programs (*.exe)')
        if path:
            self.exe_chosen.emit(name, path)
