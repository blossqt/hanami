"""The sound output, speakers or headphones: the switch between them at the top of Hanami's window
(SoundToggle), and what the sound-output hotkey says - a small pane of glass near the bottom of the
screen, naming the output the sound went to. That never takes the focus from what is in front - a
game, say - and lets the pointer through. And the microphone's mute button, beside the switch in
the edge panel (MicButton)."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import theme
from .settings import glyph_font

HEIGHT = 56
SHOWN_FOR = 1600        # ms
SPEAKER, HEADPHONES = '\uE7F5', '\uE7F6'
SIDES = ('speakers', 'headphones')
_HEADPHONE_WORDS = ('headphone', 'headset', 'earbud', 'earphone', 'airpods')


def sounds_like_headphones(name: str) -> bool:
    return any(word in name.lower() for word in _HEADPHONE_WORDS)


def glyph_for(name: str) -> str:
    return HEADPHONES if sounds_like_headphones(name) else SPEAKER


class SoundToggle(QWidget):
    """Speakers or headphones: a capsule holding both icons, the pink behind the one the sound goes
    to now, sliding across when it changes. It works as one button: clicked anywhere (or Space), it
    asks for the other one - the side the pointer lights while over it."""
    chosen = Signal(str)            # 'speakers' or 'headphones'

    WIDTH, HEIGHT = 86, 38

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAccessibleName('Sound output')
        self.side: str | None = None
        self._at: float | None = None           # where the pink is, 0 (speakers) to 1 (headphones); None: neither
        self._hover = False
        self._moving: QVariantAnimation | None = None

    def show_output(self, side: str | None, tip: str = '') -> None:
        """Which of the two the sound goes to now (None: neither), and what hovering says."""
        self.setToolTip(tip)
        self.setAccessibleDescription(side or 'neither')
        if side == self.side:
            return
        self.side = side
        if self._moving is not None:
            self._moving.stop()
        target = None if side is None else float(SIDES.index(side))
        if target is None or self._at is None or not theme.motion_on() or not self.isVisible():
            self._at = target
            self.update()
            return
        slide = QVariantAnimation(self)
        slide.setStartValue(self._at)
        slide.setEndValue(target)
        if theme.look() == 'liquid':
            spring = QEasingCurve(QEasingCurve.OutBack)
            spring.setOvershoot(1.2)
            slide.setDuration(340)
            slide.setEasingCurve(spring)
        else:
            slide.setDuration(220)
            slide.setEasingCurve(QEasingCurve.OutCubic)
        slide.valueChanged.connect(lambda v: (setattr(self, '_at', float(v)), self.update()))
        self._moving = slide
        slide.start()

    def _other(self) -> str:
        """What a click asks for: the one the sound isn't going to (the headphones, if neither)."""
        return SIDES[0] if self.side == SIDES[1] else SIDES[1]

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.chosen.emit(self._other())

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.chosen.emit(self._other())
        else:
            super().keyPressEvent(event)

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
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bend = r.height() / 2 if theme.look() == 'liquid' and theme.glass_on() else 9
        track = QPainterPath()
        track.addRoundedRect(r, bend, bend)
        painter.fillPath(track, c.chip)
        painter.setPen(QPen(c.border, 1))
        painter.drawPath(track)
        half = (r.width() - 6) / 2
        target = SIDES.index(self._other())
        if self._hover:
            spot = QRectF(r.x() + 3 + target * half, r.y() + 3, half, r.height() - 6)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 40 if theme.is_dark() else 120))
            painter.drawRoundedRect(spot, bend - 3, bend - 3)
        if self._at is not None:
            knob = QRectF(r.x() + 3 + self._at * half, r.y() + 3, half, r.height() - 6)
            painter.setPen(QPen(c.edge, 1))
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(knob, bend - 3, bend - 3)
        painter.setFont(glyph_font(13 * min(1.0, self.height() / self.HEIGHT)))
        for index, glyph in enumerate((SPEAKER, HEADPHONES)):
            lit = self._at is not None and abs(self._at - index) < 0.5
            painter.setPen(QColor(theme.ON_ACCENT) if lit else c.text if self._hover and index == target else c.dim)
            painter.drawText(QRectF(r.x() + 3 + index * half, r.y(), half, r.height()), Qt.AlignCenter, glyph)
        if self.hasFocus():
            painter.setPen(QPen(c.edge, 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(track)
        painter.end()


MIC, MIC_OFF = '', ''
MUTED = '#e03131'               # the muted microphone's red (on dark, MUTED_DARK)
MUTED_DARK = '#ff6b6b'


class MicButton(QWidget):
    """The microphone, muted or not: a button the shape of the sound switch beside it, red with the
    microphone struck through while muted. Clicked (or Space), it asks for the other."""
    clicked = Signal()

    SIZE = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAccessibleName('Microphone')
        self.muted: bool | None = None          # None: no microphone
        self._hover = False

    def show_muted(self, muted: bool | None) -> None:
        if muted != self.muted:
            self.muted = muted
            self.setAccessibleDescription('muted' if muted else 'none' if muted is None else 'on')
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.muted is not None:
            self.clicked.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and self.muted is not None:
            self.clicked.emit()
        else:
            super().keyPressEvent(event)

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
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bend = r.height() / 2 if theme.look() == 'liquid' and theme.glass_on() else 9
        shape = QPainterPath()
        shape.addRoundedRect(r, bend, bend)
        red = QColor(MUTED_DARK if theme.is_dark() else MUTED)
        if self.muted:
            fill = QColor(red)
            fill.setAlpha(70 if theme.is_dark() else 45)
            painter.fillPath(shape, fill)
            painter.setPen(QPen(red, 1))
        else:
            painter.fillPath(shape, c.chip)
            if self._hover and self.muted is not None:
                painter.fillPath(shape, QColor(255, 255, 255, 40 if theme.is_dark() else 120))
            painter.setPen(QPen(c.border, 1))
        painter.drawPath(shape)
        painter.setFont(glyph_font(13))
        if self.muted:
            painter.setPen(red)
        elif self.muted is None:
            dim = QColor(c.dim)
            dim.setAlphaF(dim.alphaF() * 0.5)
            painter.setPen(dim)
        else:
            painter.setPen(c.text if self._hover else c.dim)
        painter.drawText(r, Qt.AlignCenter, MIC_OFF if self.muted else MIC)
        if self.hasFocus():
            painter.setPen(QPen(c.edge, 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(shape)
        painter.end()


class SoundPopup(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
                         | Qt.NoDropShadowWindowHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        theme.frost(self)
        self.name = ''
        self.glyph = SPEAKER
        self._fading = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SHOWN_FOR)
        self._timer.timeout.connect(self._leave)

    def say(self, name: str, glyph: str = '') -> None:
        """Show the output's name, near the bottom of the screen the pointer is on, with its icon
        (else the one its name suggests)."""
        self.name = name
        self.glyph = glyph or glyph_for(name)
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
        painter.drawText(QRectF(18, 0, 30, HEIGHT), Qt.AlignVCenter | Qt.AlignLeft, self.glyph)
        painter.setFont(theme.font(10.5, QFont.DemiBold))
        painter.setPen(c.text)
        painter.drawText(rect.adjusted(56, 0, -18, 0), Qt.AlignVCenter | Qt.AlignLeft,
                         QFontMetrics(painter.font()).elidedText(self.name, Qt.ElideRight, int(rect.width()) - 74))
        painter.end()
