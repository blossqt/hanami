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

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
for name in ('SUITE_LOOK', 'SUITE_MODE', 'SUITE_MOTION'):
    os.environ.pop(name, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QLineEdit, QPushButton, QStyle, QToolButton,  # noqa: E402
                               QVBoxLayout, QWidget)

app = QApplication.instance() or QApplication([])

from hanami.ui import suitetheme  # noqa: E402

TEST_KEY = r'Software\blossqt\SuiteThemeTest'


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
