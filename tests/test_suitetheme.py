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
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QLineEdit, QPushButton, QStyle, QToolButton,  # noqa: E402
                               QVBoxLayout, QWidget)

app = QApplication.instance() or QApplication([])

from hanami.ui import suitetheme  # noqa: E402

TEST_KEY = r'Software\blossqt\SuiteThemeTest'
# A game really in front would quiet the glass under these tests: none is, here (GameTests stands in its own).
suitetheme.game_in_front = lambda: False


class LookTests(unittest.TestCase):
    def setUp(self):
        self._key = suitetheme._LOOK_KEY
        suitetheme._LOOK_KEY = TEST_KEY
        suitetheme._look = None

    def tearDown(self):
        suitetheme._LOOK_KEY = self._key
        suitetheme._look = None
        os.environ.pop('SUITE_LOOK', None)
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, TEST_KEY)
        except OSError:
            pass

    def test_frosted_until_chosen(self):
        self.assertEqual(suitetheme.look(), 'frosted')
        suitetheme.set_look('liquid')
        self.assertEqual(suitetheme.look(), 'liquid')
        suitetheme.set_look('nonsense')
        self.assertEqual(suitetheme.look(), 'frosted', 'an unknown look is the default one')

    def test_another_app_choosing_is_picked_up(self):
        self.assertEqual(suitetheme.look(), 'frosted')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, TEST_KEY) as key:      # as Hanami, elsewhere
            winreg.SetValueEx(key, 'Look', 0, winreg.REG_SZ, 'liquid')
        suitetheme._look_changed()                                              # what the 2 s timer does
        self.assertEqual(suitetheme.look(), 'liquid')

    def test_override_for_screenshots(self):
        os.environ['SUITE_LOOK'] = 'liquid'
        self.assertEqual(suitetheme._read_look(), 'liquid')


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


class LiquidTests(unittest.TestCase):
    """The liquid look's parts that don't need a real window: glass is pretended on."""

    def setUp(self):
        suitetheme._glass, suitetheme._look = True, 'liquid'

    def tearDown(self):
        suitetheme._glass, suitetheme._look = None, None

    def test_switches_capsules_and_glass_panels(self):
        style = suitetheme.SuiteStyle()
        self.assertEqual(style.pixelMetric(QStyle.PM_IndicatorWidth), suitetheme.SuiteStyle.SWITCH[0])
        self.assertIn('qlineargradient', suitetheme.panel_css('QFrame#card'))
        self.assertTrue(suitetheme.liquid_controls_css())
        button = QPushButton('Open')
        button.resize(80, 30)
        suitetheme._round(button)
        self.assertEqual(button.styleSheet(), 'border-radius: 15px;', 'a capsule, half as round as it is tall')
        suitetheme._look = 'frosted'
        suitetheme._round(button)
        self.assertEqual(button.styleSheet(), '', 'and plain again in the other look')
        self.assertEqual(style.pixelMetric(QStyle.PM_IndicatorWidth), suitetheme.SuiteStyle.SIZE)
        self.assertEqual(suitetheme.liquid_controls_css(), '')

    def test_an_apps_own_button_style_is_left_alone(self):
        button = QPushButton('Go')
        button.setStyleSheet('QPushButton { background: pink; }')
        button.resize(80, 30)
        suitetheme._round(button)
        self.assertEqual(button.styleSheet(), 'QPushButton { background: pink; }')

    def test_parts_qt_made_itself_get_no_light(self):
        box = QLineEdit()
        box.setClearButtonEnabled(True)
        inner = box.findChildren(QToolButton)[0]
        suitetheme._light(inner)
        self.assertFalse(getattr(inner, '_suite_lit', False))
        button = QPushButton('Mine')
        suitetheme._light(button)
        self.assertTrue(button._suite_lit)

    def test_style_sheets_follow_the_look(self):
        window = QWidget()
        suitetheme.restyle(window, suitetheme.card_style)
        self.assertIn('border-radius: 13px', window.styleSheet())
        suitetheme._look = 'frosted'
        suitetheme._suite_changed()
        self.assertNotIn('border-radius: 13px', window.styleSheet())


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

    def test_the_middle_is_clear_and_the_rim_bends_in_what_is_beyond(self):
        m = suitetheme._MARGIN
        shot = self.shot(200 + 2 * m, 120 + 2 * m)
        lens = suitetheme._lens(shot, m, m, 200, 120, suitetheme._LENSES['liquid']).toImage()
        self.assertEqual(lens.pixelColor(100, 60).name(), '#00ff00', 'the middle: what is behind, as it is')
        self.assertGreater(lens.pixelColor(0, 60).red(), 200, 'the rim: light from beyond the left edge')
        self.assertEqual(lens.pixelColor(12, 60).name(), '#00ff00', 'the bend stays at the rim')

    def test_a_framed_windows_rim_leaves_its_middle_out(self):
        m = suitetheme._MARGIN
        shot = self.shot(200 + 2 * m, 120 + 2 * m)
        lens = suitetheme._lens(shot, m, m, 200, 120, suitetheme._LENSES['rim'], rim_only=True).toImage()
        self.assertEqual(lens.pixelColor(100, 60).alpha(), 0, 'what is behind shows through, live')
        self.assertGreater(lens.pixelColor(0, 60).alpha(), 0)

    def test_tone_tells_bright_from_dark_and_calm_from_busy(self):
        calm = QPixmap(64, 64)
        calm.fill(QColor('#ffffff'))
        busy = QPixmap(64, 64)
        busy.fill(QColor('#ffffff'))
        painter = QPainter(busy)
        for x in range(0, 64, 4):
            painter.fillRect(x, 0, 2, 64, QColor('#000000'))
        painter.end()
        bright, still = suitetheme._tone(calm, QRectF(0, 0, 64, 64))
        _, lively = suitetheme._tone(busy, QRectF(0, 0, 64, 64))
        self.assertGreater(bright, 0.95)
        self.assertLess(still, 0.01)
        self.assertGreater(lively, 0.1)
        self.assertEqual(suitetheme._tone(busy.toImage(), QRectF(0, 0, 64, 64))[1], lively,
                         'the same on the glass thread, from an image')

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

    def test_one_shot_at_a_time_for_each_window(self):
        loop, came = QEventLoop(), []
        grabber = suitetheme._grabber()
        self.assertTrue(grabber.take('a', QRect(0, 0, 4, 4), 1.0, lambda image: image.size(),
                                     lambda made: (came.append(made), loop.quit())))
        self.assertFalse(grabber.take('a', QRect(0, 0, 4, 4), 1.0, lambda image: None, lambda made: None))
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        self.assertEqual(came, [QSize(4, 4)], 'taken on its own thread, handed back on this one')
        self.assertTrue(grabber.take('a', QRect(0, 0, 4, 4), 1.0, lambda image: None, lambda made: None))


class RimTests(unittest.TestCase):
    """A dragged window repaints only its rim, and its rim's light is drawn once and kept."""

    def test_only_the_rim_repaints(self):
        window = QWidget()
        window.resize(300, 200)
        changed = []
        window.update = changed.append
        suitetheme._update_rim(window)
        region = changed[0]
        span = suitetheme._RIM_SPAN
        self.assertTrue(region.contains(QPoint(2, 100)) and region.contains(QPoint(297, 100)))
        self.assertTrue(region.contains(QPoint(150, 197)), 'and along the bottom')
        self.assertFalse(region.contains(QPoint(150, 100)), 'not the middle')
        self.assertFalse(region.contains(QPoint(150, 2)), 'nor the top, under the title bar')
        self.assertFalse(region.contains(QPoint(span + 1, 100)))

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

    def test_a_framed_windows_rim_bends_in_what_is_beyond_it_in_either_look(self):
        window = QWidget()
        suitetheme.frost(window)
        with mock.patch.object(suitetheme, 'glass_on', lambda: True):
            for name in suitetheme.LOOKS:
                with mock.patch.object(suitetheme, 'look', lambda: name):
                    self.assertTrue(suitetheme._screen_glass(window), name)
        self.assertFalse(suitetheme._screen_glass(window), 'no glass, nothing taken from the screen')

    def test_the_rims_light_is_kept_until_it_moves(self):
        window = QWidget()
        window.resize(300, 200)
        edge = QRectF(0.5, 0.5, 299, 199)
        first = suitetheme._rim_light(window, edge, 8, 120, (80, 245))
        self.assertIs(suitetheme._rim_light(window, edge, 8, 120, (80, 245)), first)
        self.assertIsNot(suitetheme._rim_light(window, edge, 8, 121, (80, 245)), first, 'the light moved')
        image = suitetheme._rim_light(window, edge, 8, 121, (80, 245)).toImage()
        self.assertGreater(image.pixelColor(150, 0).alpha(), 100, 'bright at the edge')
        self.assertGreater(image.pixelColor(150, 0).alpha(), image.pixelColor(150, 5).alpha(), 'fading inwards')
        self.assertEqual(image.pixelColor(150, 100).alpha(), 0, 'nothing in the middle')


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
        try:
            with mock.patch.object(suitetheme, 'frame_interval', lambda: 4):
                suitetheme._frame_rate()
                self.assertGreater(ticks(400), 400 / 16 * 1.6, 'Qt really ticks faster than 60 a second')
        finally:
            suitetheme._frame_rate()

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
