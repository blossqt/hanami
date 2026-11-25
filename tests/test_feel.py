r"""How quickly Hanami answers, written down (feel.py) - offscreen, into a log of the test's own.

    %LOCALAPPDATA%\HanamiBuild\venv\Scripts\python.exe tests\test_feel.py
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

WORK = Path(tempfile.mkdtemp(prefix='hanami-feel-'))
os.environ.update(QT_QPA_PLATFORM='offscreen', HANAMI_FEEL_LOG=str(WORK / 'feel.log'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

qt = QApplication.instance() or QApplication([])

from hanami import feel  # noqa: E402


def spin(seconds: float) -> None:
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        qt.processEvents()
        time.sleep(0.005)


class FeelTests(unittest.TestCase):
    def setUp(self):
        self.log = feel.path()
        if self.log.exists():
            self.log.unlink()

    def lines(self) -> list[str]:
        return self.log.read_text(encoding='utf-8').splitlines() if self.log.exists() else []

    def test_a_press_is_timed_to_its_first_frame(self):
        window = QWidget()
        window.resize(200, 100)
        feel.pressed('panel', window, waited=0.02)
        window.show()
        spin(0.3)
        window.close()
        lines = [line for line in self.lines() if ' panel ' in line]
        self.assertEqual(len(lines), 1, self.lines())
        ms = int(lines[0].split('panel')[1].split('ms')[0])
        self.assertGreaterEqual(ms, 20, 'counted from when the press waited from')
        self.assertLess(ms, 1000)
        self.assertIn('painted at', lines[0])

    def test_only_the_first_frame(self):
        window = QWidget()
        feel.pressed('window', window)
        window.show()
        spin(0.2)
        window.update()
        spin(0.2)
        window.close()
        self.assertEqual(len([line for line in self.lines() if ' window ' in line]), 1)

    def test_the_thread_held_up_after_a_press_is_written_down(self):
        window = QWidget()
        feel.pressed('settings', window)
        window.show()
        spin(0.1)
        time.sleep(0.2)                         # the windows' thread held up
        spin(0.1)
        window.close()
        held = [line for line in self.lines() if 'held up' in line]
        self.assertTrue(held, self.lines())
        self.assertIn('after settings', held[0])
        ms = int(held[0].split('held up')[1].split('ms')[0])
        self.assertGreaterEqual(ms, 150)

    def test_no_window_no_line(self):
        feel.pressed('sound', None)
        spin(0.1)
        self.assertEqual(self.lines(), [])

    def test_kept_small(self):
        self.log.write_text('x' * (feel.LIMIT + 10), encoding='utf-8')
        feel.write('panel', 0.03)
        self.assertEqual(len(self.lines()), 1, 'started afresh')

    def test_a_hotkeys_wait_is_never_negative(self):
        self.assertGreaterEqual(feel.hotkey_waited(), 0.0)
        self.assertLess(feel.hotkey_waited(), 5.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
