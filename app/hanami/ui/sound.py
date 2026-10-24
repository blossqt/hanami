"""What the sound-output hotkey says: a small pane of glass near the bottom of the screen, naming
the output the sound went to. It never takes the focus from what is in front - a game, say - and
lets the pointer through."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from . import theme
from .settings import glyph_font

HEIGHT = 56
SHOWN_FOR = 1600        # ms
SPEAKER, HEADPHONES = '', ''


def glyph_for(name: str) -> str:
    lower = name.lower()
    return HEADPHONES if any(word in lower for word in ('headphone', 'headset', 'earbud', 'airpods')) else SPEAKER


class SoundPopup(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
                         | Qt.NoDropShadowWindowHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        theme.frost(self)
        self.name = ''
        self._fading = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SHOWN_FOR)
        self._timer.timeout.connect(self._leave)

    def say(self, name: str) -> None:
        """Show the output's name, near the bottom of the screen the pointer is on."""
        self.name = name
        if self._fading is not None and self._fading.state() == self._fading.State.Running:
            self._fading.stop()                             # pressed again as it went: it stays
            self._suite_closing = False
            self.setWindowOpacity(1.0)
        width = QFontMetrics(theme.font(10.5, QFont.DemiBold)).horizontalAdvance(name) + 84
        width = max(220, min(480, width))
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        self.setGeometry(area.center().x() - width // 2, area.bottom() - HEIGHT - 56, width, HEIGHT)
        if self.isVisible():
            self.update()
        else:
            self.show()
        self.raise_()
        self._timer.start()

    def _leave(self) -> None:
        self._fading = theme.fade_out(self)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        theme.paint_glass(painter, rect)
        c = theme.colors()
        painter.setFont(glyph_font(15))
        painter.setPen(QColor(theme.ink()))
        painter.drawText(QRectF(18, 0, 30, HEIGHT), Qt.AlignVCenter | Qt.AlignLeft, glyph_for(self.name))
        painter.setFont(theme.font(10.5, QFont.DemiBold))
        painter.setPen(c.text)
        painter.drawText(rect.adjusted(56, 0, -18, 0), Qt.AlignVCenter | Qt.AlignLeft,
                         QFontMetrics(painter.font()).elidedText(self.name, Qt.ElideRight, int(rect.width()) - 74))
        painter.end()
