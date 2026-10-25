"""What is pinned to the edge panel's second page: programs and files, folders and websites, chosen
in Settings > Edge panel. Each opens as a double-click in Explorer would (a website in the browser),
with Hanami's own frozen-app variables kept out of what it starts.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QFileInfo, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from .. import installer, win32
from . import theme

MOST = 10               # the panel's page holds this many, two by two
KINDS = ('file', 'folder', 'website')


@dataclass(frozen=True)
class Pin:
    kind: str           # 'file' (a program, a shortcut or any other file), 'folder' or 'website'
    target: str         # its path, or its address
    name: str

    @classmethod
    def from_dict(cls, data: dict) -> 'Pin | None':
        kind, target, name = data.get('kind'), data.get('target'), data.get('name')
        if kind not in KINDS or not isinstance(target, str) or not target:
            return None
        return cls(kind, target, name if isinstance(name, str) and name else target)

    def as_dict(self) -> dict:
        return {'kind': self.kind, 'target': self.target, 'name': self.name}


def for_path(path: str) -> Pin:
    """A file or a folder, named as Explorer shows it (a program or shortcut without its .exe or .lnk)."""
    p = Path(path)
    if p.is_dir():
        return Pin('folder', str(p), p.name or str(p))
    return Pin('file', str(p), p.stem if p.suffix.lower() in ('.exe', '.lnk', '.url') else p.name)


def for_address(text: str) -> Pin | None:
    """A website from what was typed - https:// added if no scheme was - or None if it isn't one."""
    text = text.strip()
    if not text or ' ' in text:
        return None
    if '://' not in text:
        text = 'https://' + text
    parts = urlsplit(text)
    host = (parts.hostname or '').lower()
    if parts.scheme not in ('http', 'https') or not host or ('.' not in host and host != 'localhost'):
        return None
    return Pin('website', text, host.removeprefix('www.'))


def icon(pin: Pin, size: int, ratio: float = 1.0) -> QPixmap:
    """Its icon, size px: a program's own (from its exe), a file's or folder's as Explorer shows it,
    and for a website a tile in the suite's pink with its first letter."""
    if pin.kind == 'website':
        return _letter_tile(pin.name[:1].upper() or '?', size, ratio)
    path = Path(pin.target)
    if not path.exists():
        return _letter_tile('?', size, ratio, faint=True)
    if pin.kind == 'file' and path.suffix.lower() == '.exe':
        image = win32.exe_icon(path, round(size * ratio))
        if image is not None:
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(ratio)
            return pixmap
    shown = QFileIconProvider().icon(QFileInfo(str(path)))
    pixmap = shown.pixmap(QSize(size, size), ratio)
    return pixmap if not pixmap.isNull() else _letter_tile(pin.name[:1].upper() or '?', size, ratio)


def _letter_tile(letter: str, size: int, ratio: float, faint: bool = False) -> QPixmap:
    """The suite's icon tile - the pink, rounded 42/192 - with a letter in rose."""
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(0, 0, size, size), size * 42 / 192, size * 42 / 192)
    fill = QColor(theme.ACCENT)
    if faint:
        fill.setAlpha(110)
    painter.fillPath(tile, fill)
    font = theme.font(size * 0.3, QFont.Bold)
    font.setPixelSize(max(8, round(size * 0.5)))
    painter.setFont(font)
    painter.setPen(QColor(theme.ROSE))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, letter)
    painter.end()
    return pixmap


@contextmanager
def _clean_environment():
    """Hanami's frozen-app variables out of the environment while something starts (as open_app
    starts the suite's apps): a frozen program that inherited them would try to run from Hanami's
    own files. They come back once it has started."""
    clean = installer.clean_environment()
    removed = {key: value for key, value in os.environ.items() if key not in clean}
    changed = {key: os.environ.get(key) for key, value in clean.items() if os.environ.get(key) != value}
    for key in removed:
        del os.environ[key]
    os.environ.update({key: clean[key] for key in changed})
    try:
        yield
    finally:
        for key, value in changed.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        os.environ.update(removed)


def open_pin(pin: Pin) -> str:
    """Open it, as a double-click in Explorer would; what went wrong, if anything."""
    if pin.kind != 'website' and not Path(pin.target).exists():
        return f'{pin.name} isn’t there any more.'
    folder = str(Path(pin.target).parent) if pin.kind == 'file' else None
    try:
        with _clean_environment():
            os.startfile(pin.target, cwd=folder)
    except OSError:
        return f'{pin.name} wouldn’t open.'
    return ''
