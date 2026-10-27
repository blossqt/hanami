r"""Copying text from the screen: Windows' OCR (suiteocr) on pictures drawn here, and the frozen
screen's choosing - drawn round, dragged across, clicked - offscreen, over a made-up screen.

    %LOCALAPPDATA%\HanamiBuild\venv\Scripts\python.exe tests\test_screentext.py

Nothing is shown and the real screen is never read. The clipboard is the offscreen one, this
process's own.
"""

import os
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QPA_FONTDIR', str(Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from hanami import suiteocr  # noqa: E402
from hanami.suiteocr import Line, Word  # noqa: E402
from hanami.ui import screentext  # noqa: E402

ROWS = (('Segoe UI', 9, 'Settings  General  Edge panel  Sound and mic'),
        ('Segoe UI', 11, 'Invoice A-7731 due 27 October 2026'),
        ('Microsoft YaHei', 11, '今天的作业在星期五之前交'),
        ('Segoe UI', 10, 'The quick brown fox jumps over the lazy dog'))


def page(width: int = 1200, height: int = 600) -> QImage:
    """A made-up screen: a few lines of text at a screen's sizes, on white."""
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor('white'))
    painter = QPainter(image)
    for index, (family, size, text) in enumerate(ROWS):
        font = QFont(family)
        font.setPointSize(size)
        painter.setFont(font)
        painter.setPen(QColor('#222222'))
        painter.drawText(60, 80 + index * 110, text)
    painter.end()
    return image


def spin(until, seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while not until() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


@unittest.skipUnless(suiteocr.available(), 'Windows has no text reader set up here')
class OcrTests(unittest.TestCase):
    def test_reads_a_screens_small_text(self):
        text = suiteocr.text_of(suiteocr.recognize(page()))
        self.assertIn('Settings General Edge panel Sound and mic', text, '9 pt, read at twice the size')
        self.assertIn('Invoice A-7731 due 27 October 2026', text)
        self.assertIn('The quick brown fox jumps over the lazy dog', text)

    @unittest.skipUnless(len(suiteocr.readers()) > 1, 'no Chinese, Japanese or Korean reader set up')
    def test_chinese_and_english_together(self):
        lines = [line.text for line in suiteocr.recognize(page())]
        self.assertIn('今天的作业在星期五之前交', lines, 'no spaces between the characters')
        self.assertIn('The quick brown fox jumps over the lazy dog', lines, 'English still read as English')

    @unittest.skipUnless(len(suiteocr.readers()) > 1, 'no Chinese, Japanese or Korean reader set up')
    def test_a_games_big_title(self):
        # The Chinese reader read 64 px Impact capitals as "删肅胩", which used to win.
        image = QImage(1200, 600, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor('#14202a'))
        painter = QPainter(image)
        painter.setPen(QColor('#ece4e6'))
        for family, size, y, text in (('Bahnschrift', 15, 60, 'FEATURED'), ('Impact', 64, 150, 'GRAVE MATTERS'),
                                      ('Segoe UI', 15, 230, "Don't be too scared to pick up this bundle")):
            font = QFont(family)
            font.setPixelSize(size)
            painter.setFont(font)
            painter.drawText(60, y, text)
        painter.end()
        self.assertIn('GRAVE MATTERS', [line.text for line in suiteocr.recognize(image)])

    def test_places_are_the_pictures_own(self):
        lines = suiteocr.recognize(page())
        invoice = next(line for line in lines if line.text.startswith('Invoice'))
        first = invoice.words[0]
        self.assertAlmostEqual(first.x, 60, delta=8, msg='scaled back from the enlarged picture')
        self.assertAlmostEqual(first.y + first.h, 80 + 110, delta=12)

    def test_two_pictures_at_once(self):
        # Windows' reader takes one at a time: two screens read together failed one of them.
        import threading
        found = {}

        def read(name):
            found[name] = suiteocr.text_of(suiteocr.recognize(page()))
        threads = [threading.Thread(target=read, args=(n,)) for n in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(len(found), 3)
        self.assertTrue(all('Invoice A-7731' in text for text in found.values()))

    @unittest.skipUnless(len(suiteocr.readers()) > 1, 'no Chinese, Japanese or Korean reader set up')
    def test_the_first_language_early(self):
        early = []
        lines = suiteocr.recognize(page(), early.append)
        self.assertEqual(len(early), 1)
        self.assertIn('Invoice A-7731 due 27 October 2026', [line.text for line in early[0]])
        self.assertIn('今天的作业在星期五之前交', [line.text for line in lines], 'then everything')

    def test_nothing_in_an_empty_picture(self):
        blank = QImage(400, 300, QImage.Format_ARGB32_Premultiplied)
        blank.fill(QColor('white'))
        self.assertEqual(suiteocr.recognize(blank), [])
        self.assertEqual(suiteocr.recognize(QImage()), [])


class JoiningTests(unittest.TestCase):
    def test_spaces_but_not_between_chinese_characters(self):
        words = [Word('混', 0, 0, 10, 10), Word('合', 11, 0, 10, 10), Word('text', 25, 0, 30, 10),
                 Word('和', 60, 0, 10, 10), Word('123', 75, 0, 20, 10)]
        self.assertEqual(suiteocr.join(words), '混合 text 和 123')

    def test_two_readers_put_together(self):
        english = [[Word('kå', 0, 0, 20, 10), Word('text', 25, 0, 30, 10), Word('123', 75, 0, 20, 10)],
                   [Word('def', 0, 40, 25, 10), Word('image:', 30, 40, 40, 10)]]
        chinese = [[Word('混', 0, 0, 10, 10), Word('合', 11, 0, 10, 10), Word('和', 60, 0, 10, 10)],
                   [Word('：', 62, 40, 8, 10)]]                # a colon, read as Chinese punctuation
        lines = suiteocr._together([english, chinese])
        self.assertEqual([line.text for line in lines], ['混合 text 和 123', 'def image:'])

    def test_big_capitals_stay_english(self):
        # A game's title as both readers gave it: the Chinese one took "RAV" for one character.
        english = [[Word('GRAVE', 41, 64, 146, 57), Word('MATTERS', 202, 64, 210, 60)]]
        chinese = [[Word('鼐', 102, 64, 61, 57), Word('E', 166, 64, 22, 57), Word('MATTER', 202, 64, 180, 58),
                    Word('S', 385, 65, 26, 56)]]
        self.assertEqual(suiteocr.text_of(suiteocr._together([english, chinese])), 'GRAVE MATTERS')

    def test_what_english_missed(self):
        # The English reader skipped a timer; the Chinese one read it in pieces, with wide colons.
        english = [[Word('FEATURED', 40, 32, 68, 11)]]
        chinese = [[Word('FEATURED', 40, 32, 68, 11), Word('27', 127, 32, 14, 11), Word('：', 143, 34, 2, 8),
                    Word('18', 148, 32, 14, 11), Word('：', 163, 35, 2, 7), Word('51', 167, 32, 12, 11),
                    Word('：', 183, 34, 2, 8), Word('47', 186, 32, 15, 10)],
                   [Word('完', 40, 80, 18, 18), Word('成', 60, 80, 18, 18), Word('：', 82, 86, 2, 8),
                    Word('3', 99, 80, 9, 18), Word('个', 115, 80, 19, 18)]]
        self.assertEqual(suiteocr.text_of(suiteocr._together([english, chinese])),
                         'FEATURED 27:18:51:47\n完成：3 个', 'a colon in Chinese stays wide, with no space round it')


class ShadeTests(unittest.TestCase):
    """The frozen screen, with the words as Windows would give them (no reading needed)."""

    def setUp(self):
        self.screen_text = screentext.ScreenText()
        screen = QGuiApplication.primaryScreen()
        self.picture = QPixmap.fromImage(page(screen.geometry().width(), screen.geometry().height()))
        self.picture.setDevicePixelRatio(1)
        self.real = screentext._Reader.start
        screentext._Reader.start = lambda reader, pictures: None              # read below, by hand
        self.screen_text.open({screen: self.picture})
        self.shade = self.screen_text.shades[0]
        lines = [Line((Word('Invoice', 60, 170, 70, 20), Word('A-7731', 136, 170, 60, 20),
                       Word('due', 202, 170, 30, 20))),
                 Line((Word('Total', 60, 280, 50, 20), Word('$1,249.50', 116, 280, 90, 20)))]
        self.shade.take(lines)
        QGuiApplication.clipboard().clear()

    def tearDown(self):
        screentext._Reader.start = self.real
        self.screen_text.close()
        spin(lambda: False, 0.3)

    def at(self, x, y):
        return QPointF(x, y)

    def test_drawing_round_words_chooses_them(self):
        shade = self.shade
        shade._stroke = [self.at(x, y) for x, y in ((50, 160), (210, 155), (215, 200), (55, 205), (50, 162))]
        shade._drawing = True
        shade.mouseReleaseEvent(_release(self.at(50, 162)))
        self.assertEqual(shade.text(), 'Invoice A-7731')
        self.assertTrue(shade.actions_bar.isVisibleTo(shade), 'Copy and Search come up')
        self.screen_text.copy()
        self.assertEqual(QGuiApplication.clipboard().text(), 'Invoice A-7731')

    def test_a_stroke_along_a_line_chooses_what_it_crosses(self):
        shade = self.shade
        shade._stroke = [self.at(x, 290) for x in range(100, 220, 10)]
        shade._drawing = True
        shade.mouseReleaseEvent(_release(self.at(210, 290)))
        self.assertEqual(shade.text(), 'Total $1,249.50')

    def test_dragging_across_text_chooses_it_in_order(self):
        shade = self.shade
        shade.mousePressEvent(_press(self.at(150, 180)))            # on A-7731
        self.assertEqual(shade.text(), 'A-7731')
        shade.mouseMoveEvent(_move(self.at(150, 290)))              # down to $1,249.50
        self.assertEqual(shade.text(), 'A-7731 due\nTotal $1,249.50')
        shade.mouseMoveEvent(_move(self.at(70, 180)))               # back, past where it began
        self.assertEqual(shade.text(), 'Invoice A-7731')

    def test_double_click_a_line_and_select_all(self):
        shade = self.shade
        shade.mouseDoubleClickEvent(_press(self.at(150, 290)))         # on $1,249.50
        self.assertEqual(shade.text(), 'Total $1,249.50')
        shade.choose_all()
        self.assertEqual(self.screen_text.text(), 'Invoice A-7731 due\nTotal $1,249.50')

    def test_a_click_elsewhere_lets_go(self):
        shade = self.shade
        shade.choose_all()
        shade.mousePressEvent(_press(self.at(600, 500)))
        shade.mouseReleaseEvent(_release(self.at(600, 500)))
        self.assertEqual(shade.chosen, [])
        self.assertFalse(shade.actions_bar.isVisibleTo(shade))

    def test_drawn_before_the_screen_is_read(self):
        shade = self.shade
        shade.reading, shade.words, shade.rects, shade.line_of = True, [], [], []
        shade._stroke = [self.at(x, y) for x, y in ((50, 270), (230, 265), (232, 310), (52, 312))]
        shade._drawing = True
        shade.mouseReleaseEvent(_release(self.at(52, 312)))
        self.assertEqual(shade._hint(), 'Reading the screen…')
        shade.take([Line((Word('Total', 60, 280, 50, 20), Word('$1,249.50', 116, 280, 90, 20)))])
        self.assertEqual(shade.text(), 'Total $1,249.50', 'chosen once read')

    def test_a_choice_stays_as_the_rest_is_read(self):
        shade = self.shade
        shade.reading, shade.words, shade.rects, shade.line_of, shade.chosen = True, [], [], [], []
        shade.take([Line((Word('Invoice', 60, 170, 70, 20), Word('A-7731', 136, 170, 60, 20)))], done=False)
        shade.mousePressEvent(_press(self.at(150, 180)))
        self.assertEqual(shade.text(), 'A-7731', 'chosen from the first language, before the rest')
        shade.take([Line((Word('发票', 20, 170, 30, 20), Word('Invoice', 60, 170, 70, 20),
                          Word('A-7731', 136, 170, 60, 20)))], done=True)
        self.assertEqual(shade.text(), 'A-7731', 'still chosen, by where it is')
        self.assertEqual(len(shade.words), 3)

    def test_escape_closes_without_copying(self):
        from PySide6.QtGui import QKeyEvent
        self.shade.choose_all()
        self.shade.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        self.assertFalse(self.screen_text.is_open)
        self.assertEqual(QGuiApplication.clipboard().text(), '')

    def test_search_opens_google_for_the_words(self):
        from unittest import mock
        opened = []
        self.shade.choose_all()
        with mock.patch.object(screentext.QDesktopServices, 'openUrl', lambda url: opened.append(url.toString())):
            self.screen_text.search()
        self.assertEqual(opened, ['https://www.google.com/search?q=Invoice+A-7731+due+Total+%241%2C249.50'])
        self.assertFalse(self.screen_text.is_open)

    def test_painted_with_its_choice(self):
        self.shade.choose_all()
        self.shade.resize(1200, 600)
        self.assertFalse(self.shade.grab().isNull())


class ReadingTests(unittest.TestCase):
    @unittest.skipUnless(suiteocr.available(), 'Windows has no text reader set up here')
    def test_the_frozen_screen_is_read_on_a_thread(self):
        screen = QGuiApplication.primaryScreen()
        picture = QPixmap.fromImage(page(screen.geometry().width(), screen.geometry().height()))
        screen_text = screentext.ScreenText()
        try:
            screen_text.open({screen: picture})
            shade = screen_text.shades[0]
            self.assertTrue(shade.reading)
            spin(lambda: not shade.reading)
            self.assertIn('Invoice A-7731 due 27 October 2026', [line for line in
                                                                 suiteocr.text_of(_lines(shade)).split('\n')])
        finally:
            screen_text.close()
            spin(lambda: False, 0.3)


def _lines(shade):
    rows = {}
    for word, line in zip(shade.words, shade.line_of):
        rows.setdefault(line, []).append(word)
    return [Line(tuple(words)) for _, words in sorted(rows.items())]


def _event(kind, point, buttons):
    from PySide6.QtGui import QMouseEvent
    return QMouseEvent(kind, point, point, Qt.LeftButton, buttons, Qt.NoModifier)


def _press(point):
    from PySide6.QtCore import QEvent
    return _event(QEvent.MouseButtonPress, point, Qt.LeftButton)


def _move(point):
    from PySide6.QtCore import QEvent
    return _event(QEvent.MouseMove, point, Qt.LeftButton)


def _release(point):
    from PySide6.QtCore import QEvent
    return _event(QEvent.MouseButtonRelease, point, Qt.NoButton)


if __name__ == '__main__':
    unittest.main(verbosity=2)
