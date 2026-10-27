"""Copying text from anywhere on the screen, as Android's Circle to Search does.

A hotkey freezes the screens as they are, and Windows reads the text on them (suiteocr) while
you choose some:

- draw round it - a circle, a scribble, a box - and the words inside are chosen; a stroke along
  a line of text chooses the words it crosses;
- or press on a word and drag, and the text from there to where you let go is chosen, as in a
  document. A click chooses one word, a double-click its line, Ctrl+A everything on that screen.

Copy (Enter or Ctrl+C) puts the text on the clipboard and closes; Search looks it up on Google in
the default browser. Esc, a right-click or going to another window closes without copying.

Each screen gets a window of its own over its own picture, so screens scaled differently (this
PC's second one is at 125%) each stay sharp. The pictures are taken before the windows show, and
nothing is captured while they are up. Nothing read is kept once they close.
"""

from __future__ import annotations

import math
import threading
from urllib.parse import quote_plus

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, QTimer, QUrl, QVariantAnimation, Qt, Signal
from PySide6.QtGui import (QColor, QConicalGradient, QCursor, QDesktopServices, QFont, QFontMetrics, QGuiApplication,
                           QKeySequence, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget

from .. import suiteocr
from . import theme

DIM = 0.32              # how dark the screen goes behind the choosing
APPEAR_MS = 220
SPIN_MS = 2200          # once round the glowing edge, while the screen is read
NEAR = 4                # px: a press this close to a word starts choosing text, not drawing
CLICK = 6               # px: a stroke shorter than this is a click
SEARCH = 'https://www.google.com/search?q='


def _word_rect(word, ratio: float) -> QRectF:
    """A word's place on the window, from its place in the picture (ratio: picture px per window px)."""
    return QRectF(word.x / ratio, word.y / ratio, word.w / ratio, word.h / ratio)


class _Reader(QObject):
    """suiteocr.recognize on a thread of its own, one screen after another (Windows reads one
    picture at a time), the one under the pointer first; read(shade, lines, done) back here -
    the first language's words early, then all of them."""
    read = Signal(object, object, bool)

    def start(self, pictures: list) -> None:
        """pictures: [(shade, QImage)], in the order they are to be read."""
        def work():
            for shade, image in pictures:
                try:
                    lines = suiteocr.recognize(image, lambda early, s=shade: self.read.emit(s, early, False))
                except Exception as error:  # noqa: BLE001 - said on the shade, not raised on a worker
                    print(f'screen text: {type(error).__name__}: {error}', flush=True)
                    lines = None
                self.read.emit(shade, lines, True)
        threading.Thread(target=work, daemon=True).start()


class _Actions(QFrame):
    """Copy and Search, under (or over) what is chosen."""

    def __init__(self, shade):
        super().__init__(shade)
        self.setObjectName('actions')
        theme.restyle(self, lambda: theme.card_style() + theme.panel_css('QFrame#actions', 18))
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)
        self.copy = QPushButton('Copy')
        self.copy.setProperty('role', 'primary')
        self.search = QPushButton('Search')
        for button in (self.copy, self.search):
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            row.addWidget(button)
        self.copy.clicked.connect(lambda: shade.owner.copy())
        self.search.clicked.connect(lambda: shade.owner.search())
        self.hide()


class _Shade(QWidget):
    """One screen, frozen: its picture, the text read on it, and what is chosen."""

    def __init__(self, owner, screen, picture: QPixmap):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.owner = owner
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setWindowTitle('Copy text from the screen')
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.picture = picture
        self.ratio = max(0.1, picture.width() / max(1, screen.geometry().width()))
        self._dimmed = self._dim(picture)
        self.words: list = []            # suiteocr.Word, in reading order
        self.line_of: list[int] = []     # each word's line
        self.rects: list[QRectF] = []    # each word's place on this window
        self.reading = True
        self.failed = False
        self.chosen: list[int] = []
        self._stroke: list[QPointF] = []
        self._drawing = False
        self._anchor = -1
        self._pending: list[QPointF] | None = None      # drawn before the text was read
        self.note = ''                   # 'Copied', briefly, before closing
        self._appear = 0.0
        self._phase = 0.0
        self.actions_bar = _Actions(self)
        self._fade = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=APPEAR_MS)
        self._fade.valueChanged.connect(self._appeared)
        self._spin = QTimer(self, interval=16)
        self._spin.timeout.connect(self._turn)

    @staticmethod
    def _dim(picture: QPixmap) -> QPixmap:
        dimmed = QPixmap(picture)
        painter = QPainter(dimmed)
        painter.fillRect(QRectF(0, 0, dimmed.width() / dimmed.devicePixelRatio(),
                                dimmed.height() / dimmed.devicePixelRatio()), QColor(0, 0, 0, round(255 * DIM)))
        painter.end()
        return dimmed

    def appear(self) -> None:
        self.show()
        if theme.motion_on():
            self._fade.start()
            self._spin.start()
        else:
            self._appeared(1.0)

    def _appeared(self, value) -> None:
        self._appear = float(value)
        self.update()

    def _turn(self) -> None:
        self._phase = (self._phase + 16 / SPIN_MS) % 1.0
        if not self.reading and self._phase < 16 / SPIN_MS:
            self._spin.stop()            # read: the glow settles once round
        self._update_edges()

    def _update_edges(self) -> None:
        r = self.rect()
        for strip in (QRect(0, 0, r.width(), 12), QRect(0, r.height() - 12, r.width(), 12),
                      QRect(0, 0, 12, r.height()), QRect(r.width() - 12, 0, 12, r.height())):
            self.update(strip)
        self.update(self._hint_rect())

    # ------------------------------------------------------------------ the text

    def take(self, lines, done: bool = True) -> None:
        """What Windows read on this screen (None: it couldn't be read) - early, as the first language
        read it (done False), then all of it. Whatever is chosen by then stays chosen."""
        if lines is None and not done:
            return
        if not done or self.reading or lines is None:
            held = []
        else:
            held = [self.rects[index] for index in self.chosen]
        self.reading = False
        self.failed = lines is None and not self.words
        if lines is None:
            self.update()
            return
        self.words, self.line_of = [], []
        for number, line in enumerate(lines or []):
            for word in line.words:
                self.words.append(word)
                self.line_of.append(number)
        self.rects = [_word_rect(word, self.ratio) for word in self.words]
        if held:
            self.chosen = []
            self.choose(i for i, rect in enumerate(self.rects) if any(rect.intersects(old) for old in held))
        elif self.chosen:
            self.chosen = []
        if self._pending is not None:
            stroke, self._pending = self._pending, None
            self._choose_inside(stroke)
        self.update()

    def text(self) -> str:
        lines: dict[int, list] = {}
        for index in sorted(self.chosen):
            lines.setdefault(self.line_of[index], []).append(self.words[index])
        return '\n'.join(suiteocr.join(words) for _, words in sorted(lines.items()))

    def word_at(self, point: QPointF, near: float = NEAR) -> int:
        for index, rect in enumerate(self.rects):
            if rect.adjusted(-near, -near, near, near).contains(point):
                return index
        return -1

    def _nearest(self, point: QPointF) -> int:
        """The word a drag has reached: the one under it, else the nearest on the nearest line."""
        hit = self.word_at(point)
        if hit >= 0 or not self.rects:
            return hit
        return min(range(len(self.rects)), key=lambda i: (
            max(0.0, abs(self.rects[i].center().y() - point.y()) - self.rects[i].height() / 2) * 4 +
            max(0.0, abs(self.rects[i].center().x() - point.x()) - self.rects[i].width() / 2)))

    def choose(self, indices) -> None:
        before, self.chosen = self.chosen, sorted(set(indices))
        if self.chosen:
            self.owner.chosen_on(self)
        self._place_actions()
        self._repaint(before)

    def _repaint(self, before: list[int]) -> None:
        """Only where the choice changed (and the hint, which hides behind a choice): a whole
        screen each mouse move would be a lot of drawing."""
        area = QRectF()
        for index in set(before) | set(self.chosen):            # a line's band spans all it holds
            area = area.united(self.rects[index])
        if not area.isNull():
            self.update(area.adjusted(-8, -8, 8, 8).toAlignedRect())
        self.update(self._hint_rect())

    def choose_all(self) -> None:
        self.choose(range(len(self.words)))

    def _choose_inside(self, stroke: list[QPointF]) -> None:
        """The words a drawn stroke goes round - or, drawn more like a line, the words it crosses."""
        polygon = QPolygonF(stroke)
        box = polygon.boundingRect()
        if box.width() < 14 or box.height() < 14:
            line = QPainterPath(stroke[0])
            for point in stroke[1:]:
                line.lineTo(point)
            stroker = QPainterPathStroker()
            stroker.setWidth(18)
            crossed = stroker.createStroke(line)
            self.choose(i for i, rect in enumerate(self.rects) if crossed.intersects(rect))
            return
        path = QPainterPath()
        path.addPolygon(polygon)
        path.closeSubpath()
        path.setFillRule(Qt.WindingFill)
        inside = [i for i, rect in enumerate(self.rects) if path.contains(rect.center())]
        self.choose(inside or [i for i, rect in enumerate(self.rects) if path.intersects(rect)])

    def clear_choice(self) -> None:
        before, self.chosen = self.chosen, []
        self._place_actions()
        self._repaint(before)

    def _place_actions(self) -> None:
        bar = self.actions_bar
        if not self.chosen:
            bar.hide()
            return
        area = QRectF()
        for index in self.chosen:
            area = area.united(self.rects[index])
        bar.adjustSize()
        x = round(area.center().x() - bar.width() / 2)
        y = round(area.bottom() + 14)
        if y + bar.height() > self.height() - 16:
            y = round(area.top() - 14 - bar.height())
        bar.move(max(16, min(x, self.width() - bar.width() - 16)), max(16, y))
        bar.show()
        bar.raise_()

    # ------------------------------------------------------------------ the mouse and keys

    def mousePressEvent(self, event):
        point = event.position()
        if event.button() == Qt.RightButton:
            self.owner.close()
            return
        if event.button() != Qt.LeftButton:
            return
        self.owner.chosen_on(self)
        self._anchor = self.word_at(point)
        self._stroke = [point]
        self._drawing = self._anchor < 0
        if self._anchor >= 0:
            self.choose([self._anchor])
        else:
            self.clear_choice()

    def mouseMoveEvent(self, event):
        point = event.position()
        if not event.buttons() & Qt.LeftButton:
            self.setCursor(Qt.IBeamCursor if self.word_at(point) >= 0 else Qt.CrossCursor)
            return
        if self._drawing:
            last = self._stroke[-1]
            self._stroke.append(point)
            self.update(QRectF(last, point).normalized().adjusted(-14, -14, 14, 14).toAlignedRect())
        elif self._anchor >= 0:
            reached = self._nearest(point)
            if reached >= 0:
                self.choose(range(min(self._anchor, reached), max(self._anchor, reached) + 1))

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or not self._drawing:
            return
        self._drawing = False
        stroke, self._stroke = self._stroke, []
        travelled = max((abs(p.x() - stroke[0].x()) + abs(p.y() - stroke[0].y()) for p in stroke), default=0)
        if travelled < CLICK:
            self.update()
            return
        if self.reading:
            self._pending = stroke          # chosen once the text is read
        else:
            self._choose_inside(stroke)
        self.update()

    def mouseDoubleClickEvent(self, event):
        index = self.word_at(event.position())
        if index >= 0:
            line = self.line_of[index]
            self.choose(i for i, number in enumerate(self.line_of) if number == line)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.owner.close()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter) or event.matches(QKeySequence.Copy):
            self.owner.copy()
        elif event.matches(QKeySequence.SelectAll):
            self.choose_all()
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange:
            self.owner.check_active()

    # ------------------------------------------------------------------ painting

    def _hint(self) -> str:
        if self.note:
            return self.note
        if self.chosen:
            return ''
        if self.reading:
            return 'Reading the screen…'
        if self.failed:
            return 'Windows could not read this screen'
        if not self.words:
            return 'No text on this screen'
        return 'Circle or drag across text  ·  Esc to close'

    def _hint_rect(self) -> QRect:
        metrics = QFontMetrics(theme.font(10, QFont.DemiBold))
        width = metrics.horizontalAdvance('Circle or drag across text  ·  Esc to close') + 44
        return QRect((self.width() - width) // 2, 22, width, 38)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        whole = QRectF(self.rect())
        if self._appear < 1:                 # once dark, the dark picture alone: it hides the other
            painter.drawPixmap(whole, self.picture, QRectF(self.picture.rect()))
            painter.setOpacity(self._appear)
        painter.drawPixmap(whole, self._dimmed, QRectF(self._dimmed.rect()))
        painter.setOpacity(1.0)
        self._paint_chosen(painter)
        self._paint_edges(painter)
        self._paint_stroke(painter)
        self._paint_hint(painter)
        painter.end()

    def _runs(self) -> list[QRectF]:
        """What is chosen, as one band a line - from its first word chosen to its last, as a text
        selection is - rather than a box a word."""
        runs: dict[int, QRectF] = {}
        for index in self.chosen:
            line = self.line_of[index]
            runs[line] = runs[line].united(self.rects[index]) if line in runs else QRectF(self.rects[index])
        return [rect.adjusted(-4, -3, 4, 3) for rect in runs.values()]

    def _paint_chosen(self, painter: QPainter) -> None:
        if not self.chosen:
            return
        fill = QColor(theme.ACCENT)
        fill.setAlpha(70)
        for rect in self._runs():
            source = QRectF(rect.x() * self.ratio, rect.y() * self.ratio, rect.width() * self.ratio,
                            rect.height() * self.ratio)
            painter.drawPixmap(rect, self.picture, source)            # bright again, out of the dark
            painter.setPen(QPen(QColor(theme.ROSE), 1.5))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 5, 5)

    def _paint_edges(self, painter: QPainter) -> None:
        """The glowing edge: pink running round while the screen is read, then still."""
        if self._appear <= 0:
            return
        gradient = QConicalGradient(QPointF(self.width() / 2, self.height() / 2), -self._phase * 360)
        for stop, color in ((0.0, theme.ACCENT), (0.25, '#ffffff'), (0.5, theme.ROSE), (0.75, '#ffffff'),
                            (1.0, theme.ACCENT)):
            gradient.setColorAt(stop, QColor(color))
        painter.setOpacity(self._appear * (0.95 if self.reading else 0.7))
        painter.setPen(QPen(gradient, 6))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(self.rect()).adjusted(3, 3, -3, -3))
        painter.setOpacity(1.0)

    def _paint_stroke(self, painter: QPainter) -> None:
        stroke = self._stroke if self._drawing else (self._pending or [])
        if len(stroke) < 2:
            return
        path = QPainterPath(stroke[0])
        for point in stroke[1:]:
            path.lineTo(point)
        glow = QColor(theme.ACCENT)
        glow.setAlpha(140)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(glow, 14, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)
        painter.setPen(QPen(QColor('#ffffff'), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)

    def _paint_hint(self, painter: QPainter) -> None:
        words = self._hint()
        if not words or self._appear <= 0:
            return
        c = theme.colors()
        painter.setOpacity(self._appear)
        font = theme.font(10, QFont.DemiBold)
        width = QFontMetrics(font).horizontalAdvance(words) + 44
        rect = QRectF((self.width() - width) / 2, 22, width, 38)
        card = QColor(c.card)
        card.setAlpha(235)
        painter.setPen(Qt.NoPen)
        painter.setBrush(card)
        painter.drawRoundedRect(rect, 19, 19)
        painter.setPen(c.text)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, words)
        painter.setOpacity(1.0)


class ScreenText(QObject):
    """The screens, frozen for choosing text - opened by Hanami's hotkey, and closed by it again."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.shades: list[_Shade] = []
        self._reader = _Reader(self)
        self._reader.read.connect(self._read)
        self._closing = False

    @property
    def is_open(self) -> bool:
        return bool(self.shades)

    def toggle(self) -> None:
        if self.shades:
            self.close()
        else:
            self.open()

    def open(self, pictures: dict | None = None) -> None:
        """Freeze each screen (pictures: {screen: QPixmap} in its place, for tests) and read it."""
        if self.shades:
            return
        self._closing = False
        for screen in QGuiApplication.screens():
            picture = pictures.get(screen) if pictures is not None else screen.grabWindow(0)
            if picture is None or picture.isNull():
                continue
            self.shades.append(_Shade(self, screen, picture))
        under = QGuiApplication.screenAt(QCursor.pos())
        self.shades.sort(key=lambda shade: shade.screen() is not under)
        for shade in self.shades:
            shade.appear()
        self._reader.start([(shade, shade.picture.toImage()) for shade in self.shades])   # QPixmaps stay here
        first = self.shades[0] if self.shades else None
        if first is not None:
            first.raise_()
            first.activateWindow()
            first.setFocus()

    def _read(self, shade, lines, done: bool) -> None:
        if shade in self.shades:
            shade.take(lines, done)

    def chosen_on(self, shade) -> None:
        """Text is chosen on one screen at a time."""
        for other in self.shades:
            if other is not shade and other.chosen:
                other.clear_choice()

    def text(self) -> str:
        return '\n'.join(shade.text() for shade in self.shades if shade.chosen)

    def copy(self) -> None:
        text = self.text()
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        for shade in self.shades:
            shade.note = 'Copied' if shade.chosen else ''
            shade.update()
        QTimer.singleShot(450 if theme.motion_on() else 0, self.close)

    def search(self) -> None:
        text = ' '.join(self.text().split())
        if text:
            QDesktopServices.openUrl(QUrl(SEARCH + quote_plus(text[:400])))
            self.close()

    def check_active(self) -> None:
        """Gone to another window (Alt+Tab, a click on the taskbar): close. Moving between screens
        hands the keyboard from one shade to another, so it is looked at once that has happened."""
        QTimer.singleShot(150, self._still_active)

    def _still_active(self) -> None:
        if self.shades and not self._closing and not any(shade.isActiveWindow() for shade in self.shades):
            self.close()

    def close(self) -> None:
        if self._closing or not self.shades:
            return
        self._closing = True
        shades, self.shades = self.shades, []
        for shade in shades:
            theme.fade_out(shade, shade.close, 140)
