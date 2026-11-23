r"""The suite's shared look (app/hanami/ui/suitetheme.py), offscreen.

    %LOCALAPPDATA%\HanamiBuild\venv\Scripts\python.exe tests\test_suitetheme.py

Choosing a look goes through a throwaway registry key, never the real one.
Glass itself needs a real window on Windows 11, so here it is off - as it is
in every offscreen test - and the animations run without it.
"""

import os
import sys
import time
import unittest
import winreg
from pathlib import Path
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
for name in ('SUITE_LOOK', 'SUITE_MODE', 'SUITE_MOTION'):
    os.environ.pop(name, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from PySide6.QtCore import QEventLoop, QPoint, QRect, QRectF, QSize, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QLineEdit, QPushButton, QStyle, QToolButton,  # noqa: E402
                               QVBoxLayout, QWidget)

app = QApplication.instance() or QApplication([])

from hanami.ui import suitetheme  # noqa: E402

TEST_KEY = r'Software\blossqt\SuiteThemeTest'
# A game really in front would quiet the glass under these tests: none is, here (GameTests stands in its own).
suitetheme.game_in_front = lambda: False


class LookTests(unittest.TestCase):
    """One look: frosted. Liquid glass was removed on 2026-11-20; a PC that chose it before (its
    Look still 'liquid' in the registry) is frosted all the same."""

    def setUp(self):
        self._key = suitetheme._LOOK_KEY
        suitetheme._LOOK_KEY = TEST_KEY

    def tearDown(self):
        suitetheme._LOOK_KEY = self._key
        os.environ.pop('SUITE_LOOK', None)
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
        except OSError:
            pass

    def test_frosted_whatever_was_chosen_before(self):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, TEST_KEY) as key:
            winreg.SetValueEx(key, 'Look', 0, winreg.REG_SZ, 'liquid')
        os.environ['SUITE_LOOK'] = 'liquid'
        suitetheme._look_changed()
        self.assertEqual(suitetheme.look(), 'frosted')
        self.assertEqual(list(suitetheme.LOOKS), ['frosted'])


class GlassOffscreenTests(unittest.TestCase):
    def test_no_glass_offscreen_and_colours_solid(self):
        self.assertFalse(suitetheme.glass_on())
        self.assertEqual(suitetheme.colors().card.alpha(), 255)

    def test_css_keeps_what_shows_through(self):
        self.assertEqual(suitetheme.css(QColor(255, 255, 255, 30)), '#1effffff')
        self.assertEqual(suitetheme.css(QColor('#ffd1dc')), '#ffd1dc')

    def test_check_boxes_tick_smoothly(self):
        window = QWidget()
        box = QCheckBox('Start with Windows')
        QVBoxLayout(window).addWidget(box)
        suitetheme.frost(window)
        window.show()
        app.processEvents()
        box.setChecked(True)
        steps = []
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            app.processEvents()
            value = box.property(suitetheme._TICK)
            if value is not None:
                steps.append(value)
            time.sleep(0.01)
        self.assertTrue(steps and min(steps) < 1.0, 'the tick went through steps')
        self.assertIsNone(box.property(suitetheme._TICK), 'and the box is plain again when done')
        window.close()


class ChoicesTests(unittest.TestCase):
    """Light or dark, and the animations, chosen in Hanami for the whole suite."""

    def setUp(self):
        self._key = suitetheme._LOOK_KEY
        suitetheme._LOOK_KEY = TEST_KEY
        suitetheme._look = suitetheme._mode = suitetheme._motion = None

    def tearDown(self):
        suitetheme._LOOK_KEY = self._key
        suitetheme._look = suitetheme._mode = suitetheme._motion = None
        suitetheme._app_mode = 'system'
        app.styleHints().setColorScheme(Qt.ColorScheme.Unknown)
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
        except OSError:
            pass

    # (Offscreen, Qt can't show a scheme, so these check the one asked for.)

    def test_light_or_dark_for_the_suite(self):
        self.assertEqual(suitetheme.mode(), 'system')
        self.assertEqual(suitetheme._scheme(), Qt.ColorScheme.Unknown, 'as Windows is')
        suitetheme.set_mode('dark')
        self.assertEqual(suitetheme._scheme(), Qt.ColorScheme.Dark)
        suitetheme.set_mode('light')
        self.assertEqual(suitetheme._scheme(), Qt.ColorScheme.Light)

    def test_an_apps_own_choice_wins(self):
        suitetheme.set_mode('light')
        suitetheme.app_mode('dark')
        self.assertEqual(suitetheme._scheme(), Qt.ColorScheme.Dark)
        suitetheme.app_mode('system')                       # back to the suite's
        self.assertEqual(suitetheme._scheme(), Qt.ColorScheme.Light)

    def test_animations_can_be_turned_off(self):
        self.assertTrue(suitetheme.motion_chosen())
        suitetheme.set_motion(False)
        self.assertFalse(suitetheme.motion_on())
        window = QWidget()
        box = QCheckBox('Start with Windows')
        QVBoxLayout(window).addWidget(box)
        suitetheme.frost(window)
        window.show()
        app.processEvents()
        box.setChecked(True)
        app.processEvents()
        self.assertIsNone(box.property(suitetheme._TICK), 'no animation: the box is ticked at once')
        window.close()


class GlassClearTests(unittest.TestCase):
    """How see-through the glass is: chosen in Hanami (0 to 100), its tint thinned or thickened to
    match."""

    def setUp(self):
        self._key = suitetheme._LOOK_KEY
        suitetheme._LOOK_KEY = TEST_KEY
        suitetheme._clear_value = None

    def tearDown(self):
        suitetheme._LOOK_KEY = self._key
        suitetheme._clear_value = None
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
        except OSError:
            pass

    def test_unset_it_is_as_the_glass_always_was(self):
        self.assertEqual(suitetheme.glass_clear(), suitetheme.CLEAR_DEFAULT)
        self.assertEqual(suitetheme._clear_scaled(100), 100)
        self.assertEqual(suitetheme.veil().alpha(), 112 if suitetheme.is_dark() else 64)

    def test_clearer_thins_the_tint_and_less_clear_thickens_it(self):
        suitetheme.set_glass_clear(100)
        self.assertEqual(suitetheme._clear_scaled(160), 0, 'fully clear: no tint')
        self.assertEqual(suitetheme.veil().alpha(), 0, "a window's veil too")
        suitetheme.set_glass_clear(75)
        self.assertEqual(suitetheme._clear_scaled(160), 80)
        suitetheme.set_glass_clear(0)
        self.assertEqual(suitetheme._clear_scaled(160), 255, 'twice as thick, as far as it goes')
        suitetheme.set_glass_clear(250)
        self.assertEqual(suitetheme.glass_clear(), 100, 'kept within 0 to 100')

    def test_text_behind_still_tints_it_however_clear(self):
        """At 85% the user once saw the text behind a window read as clearly as the window's own:
        what text behind adds to the tint stays, mostly, however clear the glass is chosen."""
        suitetheme.set_glass_clear(50)
        self.assertEqual(suitetheme._clear_scaled(40, 150, 235), 190, 'as it has always been')
        suitetheme.set_glass_clear(85)
        self.assertEqual(suitetheme._clear_scaled(40, 0, 235), 12, 'calm behind: clear')
        self.assertGreaterEqual(suitetheme._clear_scaled(40, 150, 235), 130, 'text behind: still tinted')

    def test_another_app_takes_it_within_seconds(self):
        suitetheme.glass_clear()
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, TEST_KEY) as key:      # as Hanami, elsewhere
            winreg.SetValueEx(key, 'GlassClear', 0, winreg.REG_DWORD, 30)
        called = []
        suitetheme.on_restyle(lambda: called.append(True))
        suitetheme._look_changed()
        self.assertEqual(suitetheme.glass_clear(), 30)
        self.assertTrue(called)


class LightTests(unittest.TestCase):
    def test_parts_qt_made_itself_get_no_light(self):
        box = QLineEdit()
        box.setClearButtonEnabled(True)
        inner = box.findChildren(QToolButton)[0]
        suitetheme._light(inner)
        self.assertFalse(getattr(inner, '_suite_lit', False))
        button = QPushButton('Mine')
        suitetheme._light(button)
        self.assertTrue(button._suite_lit)


class LensTests(unittest.TestCase):
    """Glass made from a shot of the screen."""

    @staticmethod
    def shot(width, height, left='#ff0000', middle='#00ff00'):
        """Red beyond a window's left edge, green under it."""
        pixmap = QPixmap(width, height)
        pixmap.fill(QColor(middle))
        painter = QPainter(pixmap)
        painter.fillRect(0, 0, suitetheme._MARGIN, height, QColor(left))
        painter.end()
        return pixmap

    def test_a_pop_ups_glass_is_what_is_behind_it(self):
        m = suitetheme._MARGIN
        shot = self.shot(200 + 2 * m, 120 + 2 * m)
        lens = suitetheme._lens(shot, m, m, 200, 120).toImage()
        self.assertEqual(lens.size(), QSize(200, 120))
        self.assertEqual(lens.pixelColor(100, 60).name(), '#00ff00')
        self.assertEqual(lens.pixelColor(0, 60).name(), '#00ff00', 'nothing beyond its edge is bent in')

    def test_tone_tells_bright_from_dark_and_calm_from_busy(self):
        calm = QPixmap(64, 64)
        calm.fill(QColor('#ffffff'))
        busy = QPixmap(64, 64)
        busy.fill(QColor('#ffffff'))
        painter = QPainter(busy)
        for x in range(0, 64, 4):
            painter.fillRect(x, 0, 2, 64, QColor('#000000'))
        painter.end()
        bright, still, *_ = suitetheme._tone(calm, QRectF(0, 0, 64, 64))
        _, lively, *_ = suitetheme._tone(busy, QRectF(0, 0, 64, 64))
        self.assertGreater(bright, 0.95)
        self.assertLess(still, 0.01)
        self.assertGreater(lively, 0.1)
        self.assertEqual(suitetheme._tone(busy.toImage(), QRectF(0, 0, 64, 64))[1], lively,
                         'the same on the glass thread, from an image')

    def test_words_over_part_of_a_dark_window_stay_readable_however_clear(self):
        """Half a dark window and half a white page behind a pop-up: its tint goes by the dark
        part, not the average, and keeps it even with the glass chosen fully clear."""
        half = QPixmap(64, 64)
        half.fill(QColor('#ffffff'))
        painter = QPainter(half)
        painter.fillRect(0, 0, 32, 64, QColor('#202020'))
        painter.end()
        tone = suitetheme._tone(half, QRectF(0, 0, 64, 64))
        self.assertLess(tone[2], 0.2, 'its darker part is seen')
        window = QWidget()
        window._suite_tone = tone
        with mock.patch.object(suitetheme, 'is_dark', return_value=False), \
                mock.patch.object(suitetheme, 'glass_clear', return_value=100):
            alpha = suitetheme._frost_tint(window) / 255
        self.assertGreater(tone[2] * (1 - alpha) + alpha, 0.5, 'the dark half is brought up behind dark words')
        calm = QPixmap(64, 64)
        calm.fill(QColor('#f4f4f4'))
        window._suite_tone = suitetheme._tone(calm, QRectF(0, 0, 64, 64))
        with mock.patch.object(suitetheme, 'is_dark', return_value=False), \
                mock.patch.object(suitetheme, 'glass_clear', return_value=100):
            self.assertLess(suitetheme._frost_tint(window), 10, 'a light, calm backdrop stays clear')

    def test_a_shot_is_made_into_glass_the_same_on_either_thread(self):
        m = suitetheme._MARGIN
        shot = self.shot(200 + 2 * m, 120 + 2 * m)
        want = QRect(0, 0, 200 + 2 * m, 120 + 2 * m)
        cut = QRect(0, 0, 150 + 2 * m, 120 + 2 * m)                 # cut short by the screen's edge
        for got in (want, cut):
            on_window, at, tone = suitetheme._made(shot.copy(got), got, want, 2, False, True)
            on_thread, at_too, tone_too = suitetheme._made(shot.copy(got).toImage(), got, want, 2, False, True)
            self.assertEqual(on_window.size(), want.size())
            self.assertEqual(on_thread.size(), want.size())
            self.assertEqual((at, tone), (at_too, tone_too))
        self.assertIsNone(suitetheme._made(shot, want, want, 2, True, False)[2], 'no tone asked for, none gauged')

    def test_the_image_of_something_dragged_is_taken_out_of_a_shot(self):
        shot = QPixmap(120, 80)
        shot.fill(QColor('#00ff00'))
        painter = QPainter(shot)
        painter.fillRect(40, 20, 32, 32, QColor('#ff0000'))                 # a file's image, mid-drag
        painter.end()
        healed = suitetheme._heal(shot, [QRect(40, 20, 32, 32)])
        self.assertEqual(healed.size(), shot.size())
        reds = [healed.pixelColor(x, y).red() for x in range(36, 76) for y in range(16, 56)]
        self.assertLess(max(reds), 8, 'nothing of it left: what is around it, across it')
        self.assertEqual(healed.pixelColor(56, 36).green(), 255)
        made = suitetheme._made(shot, QRect(0, 0, 120, 80), QRect(0, 0, 120, 80), 1, False, False,
                                dragged=[QRect(40, 20, 32, 32)])[0]
        self.assertLess(made.pixelColor(56, 36).red(), 8, 'and the glass made from it')
        painter = QPainter(shot)
        painter.fillRect(0, 0, 16, 80, QColor('#ff0000'))                   # one at the shot's edge
        painter.end()
        at_edge = suitetheme._heal(shot, [QRect(0, 0, 16, 80)])
        self.assertEqual(at_edge.pixelColor(8, 40).name(), '#00ff00', 'from the one side it has')

    def test_a_pop_ups_own_place_in_a_shot_is_filled_in_from_its_last_clean_one(self):
        from PySide6.QtGui import QImage
        before = QImage(300, 200, QImage.Format_RGB32)
        before.fill(QColor('#00ff00'))                                     # behind it, before it opened
        shot = QImage(300, 200, QImage.Format_RGB32)
        shot.fill(QColor('#00ff00'))
        painter = QPainter(shot)
        painter.fillRect(110, 60, 80, 60, QColor('#ff0000'))               # the pop-up, caught in the shot
        painter.fillRect(0, 0, 20, 200, QColor('#0000ff'))                 # something new beside it
        painter.end()
        want = QRect(1000, 500, 300, 200)
        covered = QRect(1110, 560, 80, 60).adjusted(-suitetheme._SHADOW, -suitetheme._SHADOW,
                                                     suitetheme._SHADOW, suitetheme._SHADOW)
        for before_at in (QPoint(1000, 500), QPoint(960, 480)):           # the last one, where it was
            clean = suitetheme._clean(QImage(shot), want, want, covered=covered, before=before, before_at=before_at)
            self.assertEqual(clean.pixelColor(150, 90).name(), '#00ff00', 'none of the pop-up in it')
            self.assertEqual(clean.pixelColor(10, 100).name(), '#0000ff', 'what changed around it, as it is now')

    def test_no_window_is_ever_left_out_of_captures(self):
        # With one left out (SetWindowDisplayAffinity), NVIDIA's desktop recording stops altogether.
        source = Path(suitetheme.__file__).read_text(encoding='utf-8')
        self.assertNotIn('SetWindowDisplayAffinity(', source)

    def test_a_pop_ups_shot_reaches_further_than_a_windows(self):
        popup = QWidget(None, Qt.FramelessWindowHint | Qt.Tool)
        popup.setGeometry(400, 300, 200, 120)
        window = QWidget()
        window.setGeometry(400, 300, 200, 120)
        for widget, margin in ((popup, suitetheme._MARGIN_FRAMELESS), (window, suitetheme._MARGIN)):
            where = suitetheme._where(widget)
            if where is not None:
                self.assertEqual(where[3], margin)
                self.assertEqual(where[2], widget.frameGeometry().adjusted(-margin, -margin, margin, margin))

    def test_a_pop_up_at_the_screens_edge_is_cleaned_before_the_edge_is_filled_out(self):
        from PySide6.QtGui import QImage
        # The edge panel sits 10 px from the screen's right edge, so want reaches 150 px past got.
        # Filling want out before taking the panel out stretched the panel itself past the edge,
        # which made _scene_changed think what was behind it had changed on every frame and heal
        # any text above it ("View dashboard") into vertical stripes down the glass.
        want = QRect(1610, 100, 460, 300)
        got = QRect(1610, 100, 310, 300)                        # the screen ends at x = 1920
        panel = QRect(1770, 160, 140, 180)
        covered = panel.adjusted(-suitetheme._SHADOW, -suitetheme._SHADOW,
                                 suitetheme._SHADOW, suitetheme._SHADOW)
        first = QImage(got.size(), QImage.Format_RGB32)
        first.fill(QColor('#00ff00'))
        p = QPainter(first)
        for x in range(150, 220, 4):                            # fine text above the panel, inside covered's x
            p.fillRect(x, 30, 2, 6, QColor('#0044ff'))
        p.end()
        before = suitetheme._clean(first, got, want)            # taken before the panel was on screen
        later = QImage(first)
        p = QPainter(later)
        p.fillRect(covered.translated(-got.topLeft()).intersected(later.rect()), QColor('#005500'))     # its shadow
        p.fillRect(panel.translated(-got.topLeft()), QColor('#ff0000'))                                 # the panel
        p.end()
        clean = suitetheme._clean(later, got, want, covered=covered, before=before, before_at=want.topLeft())
        self.assertEqual(clean.size(), want.size())
        self.assertEqual(clean.pixelColor(200, 150).name(), '#00ff00', 'the panel taken out, from before')
        self.assertEqual(clean.pixelColor(360, 150).name(), '#00ff00', 'beyond the screen edge: no stretched panel')

    def test_watching_around_a_still_pop_up_leaves_its_own_shadow_out(self):
        self.assertGreaterEqual(suitetheme._AROUND[0], suitetheme._SHADOW,
                                'what _watch_around looks at lies outside the pop-up’s own shadow')

    def test_healing_a_changed_scene_blends_smoothly_without_stripes(self):
        from PySide6.QtGui import QImage
        shot = QImage(200, 200, QImage.Format_RGB32)
        shot.fill(QColor('#ffffff'))
        p = QPainter(shot)
        for x in range(40, 120, 4):                             # sharp dark letters just above the healed part
            p.fillRect(x, 26, 2, 3, QColor('#000000'))
        p.fillRect(30, 30, 140, 140, QColor('#ff0000'))
        p.end()
        healed = suitetheme._heal(shot, [QRect(30, 30, 140, 140)])
        row = [healed.pixelColor(x, 80).lightness() for x in range(45, 115)]
        steps = [abs(a - b) for a, b in zip(row, row[1:])]
        self.assertLess(max(steps), 10, f'smoothed across, no 1 px stripes: {steps[:12]}')

    def test_one_shot_at_a_time_for_each_window(self):
        from PySide6.QtGui import QImage
        loop, came = QEventLoop(), []
        grabber = suitetheme._grabber()
        no_screen = suitetheme._screen_image(QRect(0, 0, 4, 4)) is None
        patch = (mock.patch.object(suitetheme, '_screen_image',
                                   lambda r: QImage(r.width(), r.height(), QImage.Format_RGB32))
                 if no_screen else mock.MagicMock())
        with patch:
            self.assertTrue(grabber.take('a', QRect(0, 0, 4, 4), 1.0, lambda image: image.size(),
                                         lambda made: (came.append(made), loop.quit())))
            self.assertFalse(grabber.take('a', QRect(0, 0, 4, 4), 1.0, lambda image: None, lambda made: None))
            QTimer.singleShot(3000, loop.quit)
            loop.exec()
            self.assertEqual(came, [QSize(4, 4)], 'taken on its own thread, handed back on this one')
            self.assertTrue(grabber.take('a', QRect(0, 0, 4, 4), 1.0, lambda image: None, lambda made: None))


class RimTests(unittest.TestCase):
    """A framed window opens over glass of its own until Windows has its Acrylic up."""

    def test_a_frosted_window_opens_over_glass_of_its_own_until_windows_has_its_acrylic_up(self):
        window = QWidget()
        window.resize(200, 120)
        shot = QPixmap(200, 120)
        shot.fill(QColor('#ff0000'))
        suitetheme._bridge_from(window, shot)
        glass = window._suite_bridge.toImage()
        self.assertEqual(glass.size(), shot.size())
        self.assertLess(glass.pixelColor(100, 60).red(), 255, 'tinted, as Acrylic is')
        self.assertGreater(glass.pixelColor(100, 60).red(), glass.pixelColor(100, 60).green(), 'what is behind shows')
        loop = QEventLoop()
        QTimer.singleShot(suitetheme._BRIDGE_HOLD + suitetheme._BRIDGE_FADE + 300, loop.quit)
        loop.exec()
        self.assertIsNone(window._suite_bridge, 'gone once the Acrylic is up')

    def test_its_glass_while_it_opens_comes_from_its_rims_shot(self):
        window = QWidget()
        window.setGeometry(300, 200, 200, 120)
        m = suitetheme._MARGIN
        shot = QPixmap(200 + 2 * m, 120 + 2 * m)
        shot.fill(QColor('#0000ff'))
        painter = QPainter(shot)
        painter.fillRect(m, m, 200, 120, QColor('#ff0000'))                 # what is behind the window
        painter.end()
        window._suite_shot, window._suite_shot_at = shot, window.geometry().topLeft() - QPoint(m, m)
        suitetheme._bridge(window)
        glass = window._suite_bridge.toImage()
        self.assertEqual(glass.size(), QSize(200, 120))
        middle = glass.pixelColor(100, 60)
        self.assertGreater(middle.red(), middle.blue(), 'what is behind the window, not beside it')

    def test_a_framed_window_takes_what_is_behind_it_as_it_opens(self):
        window = QWidget()
        suitetheme.frost(window)
        with mock.patch.object(suitetheme, 'glass_on', lambda: True):
            self.assertTrue(suitetheme._screen_glass(window), 'for the glass it opens over')
        self.assertFalse(suitetheme._screen_glass(window), 'no glass, nothing taken from the screen')


class SmoothResizeTests(unittest.TestCase):
    def test_a_stack_of_pages_answers_for_its_page_in_sight_only(self):
        pages = suitetheme.Pages()
        tall, short = QWidget(), QWidget()
        for page, height in ((tall, 900), (short, 100)):
            QVBoxLayout(page).addWidget(_Tall(height))
            pages.addWidget(page)
        pages.setCurrentWidget(short)
        own = short.layout().totalHeightForWidth(300)               # its words and its margins
        self.assertLess(own, 200)
        self.assertEqual(pages.layout().heightForWidth(300), own, 'the hidden tall page left out')
        self.assertEqual(tall.heightForWidth(300), -1)
        pages.setCurrentWidget(tall)
        self.assertGreater(pages.layout().heightForWidth(300), 900)

    def test_colours_are_kept_not_made_on_every_ask(self):
        self.assertIs(suitetheme.colors(), suitetheme.colors())


class _Tall(QWidget):
    def __init__(self, height: int):
        super().__init__()
        self._height = height
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._height


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class GameTests(unittest.TestCase):
    """Keeping quiet while a full-screen game is in front. No game is ever really in front here:
    which window is, is a stand-in."""

    def setUp(self):
        self._key = suitetheme._LOOK_KEY
        suitetheme._LOOK_KEY = TEST_KEY
        self.in_front = False
        self._patch = mock.patch.object(suitetheme, 'game_in_front', lambda: self.in_front)
        self._patch.start()
        suitetheme._check_game()

    def tearDown(self):
        self._patch.stop()
        suitetheme._game_callbacks.clear()
        suitetheme._LOOK_KEY = self._key
        suitetheme._game_quiet = False
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
        except OSError:
            pass

    def test_apps_hear_when_a_game_comes_and_goes(self):
        heard = []
        suitetheme.on_game(heard.append)
        self.assertFalse(suitetheme.quiet_now())
        self.in_front = True
        suitetheme._check_game()
        self.assertTrue(suitetheme.quiet_now())
        suitetheme._check_game()                                # still there: said once
        self.in_front = False
        suitetheme._check_game()
        self.assertEqual(heard, [True, False])

    def test_not_when_turned_off(self):
        self.assertTrue(suitetheme.game_quiet_chosen(), 'on until turned off')
        suitetheme.set_game_quiet(False)
        self.in_front = True
        suitetheme._check_game()
        self.assertFalse(suitetheme.quiet_now())
        suitetheme.set_game_quiet(True)
        self.assertTrue(suitetheme.quiet_now(), 'turning it on takes effect at once')

    def test_grabbits_downloads_slow_down_unless_chosen_otherwise(self):
        self.assertEqual(suitetheme.game_downloads(), 'slow')
        suitetheme.set_game_downloads('pause')
        self.assertEqual(suitetheme.game_downloads(), 'pause')
        suitetheme.set_game_downloads('nonsense')
        self.assertEqual(suitetheme.game_downloads(), 'slow')

    def test_the_glass_takes_no_shots_of_a_game(self):
        window = QWidget()
        window.resize(200, 120)
        self.in_front = True
        suitetheme._check_game()
        with mock.patch.object(suitetheme, '_where', lambda w: self.fail('looked at the screen')):
            suitetheme._capture(window)
            self.assertTrue(suitetheme._capture_later(window, final=True))

    def test_games_are_the_ones_windows_knows(self):
        games = suitetheme._known_games()
        self.assertTrue(all(path == os.path.normcase(path) for path in games))
        self.assertIsInstance(suitetheme._program_of(os.getpid()), str)


class MotionTests(unittest.TestCase):
    """The animations that came with 2026-10-24: parts rising into place, pop-ups fading out and
    progress gliding."""

    def setUp(self):
        self._key = suitetheme._LOOK_KEY
        suitetheme._LOOK_KEY = TEST_KEY
        suitetheme._motion = None

    def tearDown(self):
        suitetheme._LOOK_KEY = self._key
        suitetheme._motion = None
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
        except OSError:
            pass

    def test_they_move_on_once_a_frame_on_the_fastest_screen(self):
        from PySide6.QtCore import QVariantAnimation

        class Screen:
            def __init__(self, rate):
                self.refreshRate = lambda: rate
        with mock.patch.object(suitetheme.QGuiApplication, 'screens', lambda: [Screen(100.0), Screen(280.0)]):
            self.assertEqual(suitetheme.frame_interval(), 3)
        with mock.patch.object(suitetheme.QGuiApplication, 'screens', lambda: [Screen(59.94)]):
            self.assertEqual(suitetheme.frame_interval(), 16, 'as Qt has it')

        def ticks(ms):
            animation = QVariantAnimation()
            animation.setDuration(ms)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            count = [0]
            animation.valueChanged.connect(lambda _: count.__setitem__(0, count[0] + 1))
            loop = QEventLoop()
            animation.finished.connect(loop.quit)
            animation.start()
            loop.exec()
            return count[0]
        suitetheme._honour_timers()             # as install() does: no window here is ever in sight
        try:
            with mock.patch.object(suitetheme, 'frame_interval', lambda: 4):
                suitetheme._frame_rate()
                self.assertGreater(ticks(400), 400 / 16 * 1.6, 'Qt really ticks faster than 60 a second')
        finally:
            suitetheme._frame_rate()

    def test_the_wheel_glides(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QListWidget, QScrollArea
        suitetheme.install(app) if suitetheme._wheels_filter is None else None
        area = QScrollArea()
        inside = QWidget()
        inside.setFixedSize(300, 3000)
        area.setWidget(inside)
        area.resize(320, 300)
        area.show()
        app.processEvents()
        bar = area.verticalScrollBar()

        def wheel(widget, y=-120, pixels=QPoint(0, 0), modifiers=Qt.NoModifier):
            event = QWheelEvent(QPointF(20, 20), QPointF(20, 20), pixels, QPoint(0, y), Qt.NoButton,
                                modifiers, Qt.NoScrollPhase, False)
            QApplication.sendEvent(widget, event)
            return event
        step = QApplication.wheelScrollLines() * bar.singleStep()
        wheel(area.viewport())
        self.assertLess(bar.value(), step, 'not there at once')
        _wait(suitetheme.SCROLL_MS // 3)
        self.assertTrue(0 < bar.value() < step, 'on its way')
        wheel(area.viewport())                      # a second notch, while the first glides
        _wait(suitetheme.SCROLL_MS + 120)
        self.assertEqual(bar.value(), 2 * step, 'both notches, as Qt goes: no further, no less')
        bar.setValue(0)
        wheel(area.viewport(), pixels=QPoint(0, -40), y=-40)
        self.assertGreater(bar.value(), 0, "a touchpad's own smooth scrolling: Qt's, at once")
        bar.setValue(0)
        wheel(area.viewport(), y=120)
        _wait(60)
        self.assertEqual(bar.value(), 0, 'at the top, up: nothing, and the wheel goes on to what holds it')
        wheel(area.viewport())
        _wait(40)
        bar.setValue(1000)                          # moved meanwhile (a jump to an item, say)
        _wait(suitetheme.SCROLL_MS)
        self.assertEqual(bar.value(), 1000, 'the glide gives way')
        rows = QListWidget()
        rows.addItems([f'Row {n}' for n in range(200)])
        rows.resize(200, 200)
        rows.show()
        app.processEvents()
        wheel(rows.viewport())
        _wait(suitetheme.SCROLL_MS + 120)
        self.assertEqual(rows.verticalScrollMode(), rows.ScrollMode.ScrollPerPixel, 'a list by the pixel')
        self.assertEqual(rows.verticalScrollBar().value(), QApplication.wheelScrollLines() * rows.sizeHintForRow(0),
                         'three rows a notch, as before - from the first notch on')
        with mock.patch.object(suitetheme, 'motion_on', lambda: False):
            bar.setValue(0)
            wheel(area.viewport())
            self.assertEqual(bar.value(), step, 'animations off: at once, as Qt does it')
        area.close()
        rows.close()

    def test_a_button_brightens_under_the_pointer_in_frosted(self):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QEnterEvent
        with mock.patch.object(suitetheme, 'motion_on', lambda: True):
            window = QWidget()
            button = QPushButton('Open', window)
            button.resize(100, 32)
            suitetheme.frost(window)
            window.show()
            app.processEvents()
            plain = button.grab().toImage()
            from PySide6.QtGui import QHoverEvent
            QApplication.sendEvent(button, QHoverEvent(QEvent.HoverEnter, QPointF(50, 16), QPointF(50, 16), QPointF(-1, -1)))
            state = getattr(button, suitetheme._LIGHT)
            self.assertLess(state['hover'], 0.5, 'not at once')
            _wait(250)
            self.assertAlmostEqual(state['hover'], 1.0, places=2)
            self.assertNotEqual(button.grab().toImage(), plain, 'drawn lighter')
            QApplication.sendEvent(button, QHoverEvent(QEvent.HoverLeave, QPointF(-1, -1), QPointF(-1, -1), QPointF(50, 16)))
            _wait(400)
            self.assertLess(state['hover'], 0.01, 'and back')
            window.close()

    def test_menus_and_lists_slide_open_with_animations_on(self):
        with mock.patch.object(suitetheme, 'motion_on', lambda: True):
            suitetheme._ui_effects()
            self.assertTrue(QApplication.isEffectEnabled(Qt.UI_AnimateCombo))
            self.assertTrue(QApplication.isEffectEnabled(Qt.UI_FadeMenu))
        with mock.patch.object(suitetheme, 'motion_on', lambda: False):
            suitetheme._ui_effects()
            self.assertFalse(QApplication.isEffectEnabled(Qt.UI_AnimateMenu))
        suitetheme._ui_effects()

    def test_a_windows_parts_rise_into_place_one_after_another(self):
        window = QWidget()
        layout = QVBoxLayout(window)
        parts = [QPushButton(f'Part {n}') for n in range(3)]
        for part in parts:
            layout.addWidget(part)
        suitetheme.frost(window)
        window.show()
        app.processEvents()
        effects = [part.graphicsEffect() for part in parts]
        self.assertTrue(all(isinstance(e, suitetheme._Rise) for e in effects), 'each comes in')
        _wait(80)
        self.assertGreater(effects[0].step, effects[2].step, 'the first is further along')
        where = [part.pos() for part in parts]
        _wait(500)
        self.assertEqual([part.graphicsEffect() for part in parts], [None] * 3, 'and is left as it was')
        self.assertEqual([part.pos() for part in parts], where, 'drawn so, never moved')
        window.close()

    def test_a_pages_sections_rise_as_it_comes_up(self):
        from PySide6.QtWidgets import QFrame, QStackedWidget
        window = QWidget()
        stack = QStackedWidget()
        QVBoxLayout(window).addWidget(stack)
        stack.addWidget(QWidget())
        page = QWidget()
        sections = []
        for _ in range(2):
            frame = QFrame()
            frame.setObjectName('section')
            QVBoxLayout(page).addWidget(frame) if not sections else page.layout().addWidget(frame)
            sections.append(frame)
        stack.addWidget(page)
        suitetheme.frost(window)
        window.show()
        _wait(500)
        stack.setCurrentIndex(1)
        self.assertTrue(all(isinstance(s.graphicsEffect(), suitetheme._Rise) for s in sections))
        window.close()

    def test_a_rising_part_is_drawn_lower_and_fainter(self):
        window = QWidget()
        window.resize(60, 70)
        window.setStyleSheet('background: white')
        part = QWidget(window)
        part.setGeometry(0, 0, 40, 40)
        part.setStyleSheet('background: red')
        effect = suitetheme._Rise(part, 10)
        part.setGraphicsEffect(effect)
        effect.step = 0.5
        window.show()
        app.processEvents()
        picture = window.grab().toImage()
        self.assertEqual(picture.pixelColor(20, 2), QColor('white'), 'its top is lower')
        faint = picture.pixelColor(20, 25)
        self.assertTrue(faint.red() == 255 and 100 < faint.green() < 160, f'half there: {faint.name()}')
        window.close()

    def test_a_pop_up_fades_out_then_closes(self):
        window = QWidget(None, Qt.FramelessWindowHint | Qt.Tool)
        window.resize(100, 60)
        window.show()
        app.processEvents()
        closed = []
        suitetheme.fade_out(window, lambda: (closed.append(True), window.hide()))
        suitetheme.fade_out(window)                             # asked again meanwhile: once is enough
        self.assertTrue(window.isVisible(), 'still there, fading')
        _wait(300)
        self.assertEqual(closed, [True])
        self.assertFalse(window.isVisible())
        self.assertEqual(window.windowOpacity(), 1.0, 'ready to be shown again')

    def test_at_once_with_animations_off(self):
        suitetheme.set_motion(False)
        window = QWidget(None, Qt.FramelessWindowHint | Qt.Tool)
        window.show()
        app.processEvents()
        suitetheme.fade_out(window)
        self.assertFalse(window.isVisible())

    def test_progress_glides_forward_and_jumps_back(self):
        from PySide6.QtWidgets import QProgressBar
        window = QWidget()
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        QVBoxLayout(window).addWidget(bar)
        suitetheme.frost(window)
        window.show()
        app.processEvents()
        bar.setValue(80)
        app.processEvents()
        self.assertLess(bar.value(), 80, 'on its way')
        _wait(450)
        self.assertEqual(bar.value(), 80, 'and there')
        bar.setValue(10)
        self.assertEqual(bar.value(), 10, 'going back is at once')
        window.close()



class SerifTests(unittest.TestCase):
    def test_headings_are_geist_serif(self):
        self.assertEqual(suitetheme.serif(20).family(), 'Geist Serif')
        self.assertEqual(suitetheme.serif(20).pointSizeF(), 20)

    def test_without_the_file_headings_are_segoe(self):
        with mock.patch.object(suitetheme, '_serif', ['']):
            self.assertEqual(suitetheme.serif(17).weight(), QFont.DemiBold)


class ScaleTests(unittest.TestCase):
    """The suite's one scale of text, gaps and timings (2026-11-01)."""

    def test_roles(self):
        self.assertEqual(suitetheme.text('body').pointSizeF(), suitetheme.TYPE['body'])
        self.assertEqual(suitetheme.text('title').family(), 'Geist Serif')
        self.assertNotEqual(suitetheme.text('caption').family(), 'Geist Serif')
        self.assertLess(suitetheme.QUICK, suitetheme.STEADY)
        self.assertLess(suitetheme.STEADY, suitetheme.GENTLE)
        self.assertTrue(all(step % 4 == 0 for step in suitetheme.SPACE))

    def test_figures_are_one_width(self):
        from PySide6.QtGui import QFontMetricsF
        metrics = QFontMetricsF(suitetheme.font(9.5))
        self.assertEqual({round(metrics.horizontalAdvance(d), 2) for d in '0123456789'}.__len__(), 1)


class WallTests(unittest.TestCase):
    def test_tint_leans_to_the_wallpaper(self):
        with mock.patch.object(suitetheme, '_wall', None):
            self.assertEqual(suitetheme.walled(QColor(255, 255, 255, 80)), QColor(255, 255, 255, 80))
        with mock.patch.object(suitetheme, '_wall', QColor('#3366cc')):
            tinted = suitetheme.walled(QColor(255, 255, 255, 80))
            self.assertEqual(tinted.alpha(), 80)
            self.assertGreater(tinted.blue(), tinted.red())       # blue-ish, still nearly white
            self.assertGreater(tinted.lightnessF(), 0.9)
            dark = suitetheme.walled(QColor(10, 10, 12, 112))
            self.assertLess(dark.lightnessF(), 0.15)

    def test_no_wallpaper_read_offscreen(self):
        with mock.patch.object(suitetheme, '_wall', None), mock.patch.object(suitetheme, '_suite_changed') as changed:
            suitetheme._look_at_wall()
            changed.assert_not_called()


class NoOutlineTests(unittest.TestCase):
    def test_no_focus_rectangle_is_drawn(self):
        from unittest.mock import MagicMock
        from PySide6.QtWidgets import QStyle, QStyleOption
        painter = MagicMock()
        suitetheme.SuiteStyle().drawPrimitive(QStyle.PE_FrameFocusRect, QStyleOption(), painter)
        painter.assert_not_called()

    def test_nothing_rings_what_the_keyboard_reaches(self):
        self.assertFalse(hasattr(suitetheme, '_Focus'))
        self.assertFalse(hasattr(suitetheme, '_Ring'))


class PressTests(unittest.TestCase):
    def test_a_pressed_button_gives_and_keeps_its_words(self):
        window = QWidget()
        window.setStyleSheet('QWidget { background: #3a5560; } QPushButton { color: white; }')
        layout = QVBoxLayout(window)
        button = QPushButton('Press')
        button.setFixedSize(120, 34)
        layout.addWidget(button)
        window.resize(160, 60)
        button.installEventFilter(suitetheme._lights())
        state = suitetheme._Light._state(button)
        plain = button.grab().toImage()
        with mock.patch.object(suitetheme, 'motion_on', return_value=True):
            state['press'] = 1.0
            suitetheme._sink(button, True)
            effect = button.graphicsEffect()
            self.assertIsInstance(effect, suitetheme._Sink)
            self.assertLess(effect.scale(), 1.0)
            self.assertGreater(effect.scale(), 0.95)
            pressed = window.grab().toImage()
            # its words are still drawn (0.1.52 lost them): light pixels in the button's middle
            centre = button.geometry().center()
            self.assertTrue(any(QColor(pressed.pixel(x, centre.y())).lightness() > 180
                                for x in range(centre.x() - 20, centre.x() + 20)))
            state['press'] = 0.0
            suitetheme._sink(button, False)
            self.assertIsNone(button.graphicsEffect())
        self.assertFalse(plain.isNull())
        window.close()

    def test_a_menu_button_lets_go_once_its_menu_closes(self):
        """A ⋯ button opens its menu as it is pressed, so its release goes to the menu: it stayed
        shaded and lit after the menu closed, with the pointer long gone."""
        from PySide6.QtCore import QEvent, QPoint, QPointF
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QMenu
        window = QWidget()
        button = QToolButton(window)
        button.resize(28, 20)
        menu = QMenu(button)
        menu.addAction('Release notes')
        button.setMenu(menu)
        button.installEventFilter(suitetheme._lights())
        window.show()
        app.processEvents()
        elsewhere = button.mapToGlobal(QPoint(400, 400))
        with mock.patch.object(suitetheme, 'motion_on', return_value=True), \
                mock.patch.object(suitetheme.QCursor, 'pos', return_value=elsewhere):
            state = suitetheme._Light._state(button)
            state['hover'] = 1.0
            button.setAttribute(Qt.WA_UnderMouse, True)
            press = QMouseEvent(QEvent.MouseButtonPress, QPointF(14, 10), QPointF(14, 10), Qt.LeftButton,
                                Qt.LeftButton, Qt.NoModifier)
            suitetheme._lights().eventFilter(button, press)     # as the press opens the menu
            _wait(200)
            self.assertGreater(state['press'], 0.5)
            menu.aboutToHide.emit()                             # the menu closes: no release ever comes
            _wait(600)
            self.assertLess(state['press'], 0.01, 'eased back as if let go')
            self.assertLess(state['hover'], 0.01, 'and no longer lit, the pointer being elsewhere')
            self.assertFalse(button.testAttribute(Qt.WA_UnderMouse))
        window.close()


class IconTests(unittest.TestCase):
    def test_one_set(self):
        from hanami.ui import suiteicons
        for name in ('gear', 'speaker', 'headphones', 'mic', 'mic_off', 'sliders', 'check', 'info', 'trash'):
            self.assertFalse(suiteicons.pixmap(name, '#c2255c', 18).isNull(), name)
        self.assertTrue(suiteicons.pixmap('no such icon', '#000000').isNull())


class PlaceTests(unittest.TestCase):
    def test_offscreen_windows_keep_no_place(self):
        self.assertIsNone(suitetheme._place_name(QWidget()))      # tests never write the person's registry


if __name__ == '__main__':
    unittest.main(verbosity=2)
