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
os.environ.pop('SUITE_LOOK', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QVBoxLayout, QWidget  # noqa: E402

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
