"""Monitors' brightness over DDC/CI (brightness.py).

Never change the user's real brightness in a test: on the real monitors, setting each to the
brightness it has already proves the call.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from hanami import brightness  # noqa: E402


class _Ddc:
    """Monitors of the test's own - (key, name, corner, handle) and, by handle, (brightness, most)
    or None for one that doesn't answer - as slow to set as real ones."""

    def __init__(self, monitors, readings):
        self.monitors, self.readings, self.sent, self.asked = monitors, readings, [], []

    def open(self):
        return list(self.monitors)

    def read(self, handle):
        self.asked.append(handle)
        return self.readings.get(handle)

    def set(self, handle, value):
        self.sent.append((handle, value))
        time.sleep(0.05)
        return True


class MonitorsTests(unittest.TestCase):
    def watch(self, monitors, readings):
        got, done = [], threading.Event()
        watched = brightness.Monitors(lambda found: (got.append(found), done.set()), _Ddc(monitors, readings))

        def look():
            done.clear()
            watched.look()
            self.assertTrue(done.wait(5))
            return got[-1]
        return watched, look

    def test_named_and_in_order_across_the_desk(self):
        _, look = self.watch([(r'\\.\DISPLAY2#0', 'DELL G2524H', (0, 0), 2), (r'\\.\DISPLAY1#0', 'TYPEC', (-1920, 0), 1),
                              (r'\\.\DISPLAY3#0', '', (2560, 0), 3), (r'\\.\DISPLAY4#0', 'DELL G2524H', (5120, 0), 4),
                              (r'\\.\DISPLAY5#0', 'No DDC/CI', (7680, 0), 5)],
                             {1: (30, 50), 2: (70, 100), 3: (100, 100), 4: (0, 100)})
        self.assertEqual([(m.name, m.value) for m in look()],
                         [('TYPEC', 60), ('DELL G2524H', 70), ('Screen 3', 100), ('DELL G2524H 2', 0)],
                         'left to right, as a share of each one’s own most; none for one that doesn’t answer')

    def test_a_dragged_slider_sends_no_more_than_the_monitor_takes(self):
        watched, look = self.watch([(r'\\.\DISPLAY1#0', 'TYPEC', (0, 0), 7)], {7: (30, 50)})
        key = look()[0].key
        ddc = watched._ddc
        for percent in range(10, 61, 10):
            watched.set(key, percent)
        until = time.monotonic() + 5
        while time.monotonic() < until and (not ddc.sent or ddc.sent[-1] != (7, 30)):
            time.sleep(0.02)
        self.assertEqual(ddc.sent[-1], (7, 30), 'the last asked for, of its most: 60% of 50')
        self.assertLess(len(ddc.sent), 6, 'those overtaken while one was sent were never sent')
        watched.set('not a monitor', 50)
        time.sleep(0.2)
        self.assertEqual(ddc.sent[-1], (7, 30), 'one not found is left alone')

    def test_one_just_set_or_not_answering_keeps_its_slider(self):
        watched, look = self.watch([(r'\\.\DISPLAY1#0', 'TYPEC', (0, 0), 7)], {7: (30, 50)})
        key = look()[0].key
        ddc = watched._ddc
        watched.set(key, 80)
        ddc.asked.clear()
        self.assertEqual([m.value for m in look()], [80], 'just set: as it was set')
        self.assertEqual(ddc.asked, [], 'and not asked - it wouldn’t answer yet')
        watched._set_at[key] -= brightness.SETTLE
        ddc.readings[7] = None
        self.assertEqual([m.value for m in look()], [80], 'not answering: as it last was')
        self.assertEqual(ddc.asked, [7])


class RealTests(unittest.TestCase):
    def test_the_monitors_here(self):
        ddc = brightness._Ddc()
        try:
            found = [(name, handle, ddc.read(handle)) for key, name, corner, handle in ddc.open()]
            found = [(name, handle, reading) for name, handle, reading in found if reading is not None]
            if not found:
                self.skipTest('no monitor here answers DDC/CI')
            for name, handle, (current, most) in found:
                self.assertTrue(0 <= current <= most, (name, current, most))
                self.assertTrue(ddc.set(handle, current), f'{name}: set to what it is')
                until, again = time.monotonic() + 3, None
                while again is None and time.monotonic() < until:
                    again = ddc.read(handle)
                self.assertEqual(again, (current, most), f'{name}: answering again within {brightness.SETTLE} s')
        finally:
            ddc.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
