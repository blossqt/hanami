r"""The shared crash log (suitelog.py), in a child Python that has no stderr, like a windowed exe.

    %LOCALAPPDATA%\HanamiBuild\venv\Scripts\python.exe tests\test_suitelog.py

Standard library only, like suitelog itself.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHILD = '''
import sys
sys.path.insert(0, {app!r})
if {windowed}:
    sys.stdout = sys.stderr = None          # what a windowed exe starts with
from hanami import suitelog
print('log at', suitelog.start('Crashy'))
{then}
'''


class SuiteLogTest(unittest.TestCase):
    def setUp(self):
        self.local = Path(tempfile.mkdtemp(prefix='suitelog-'))
        self.addCleanup(shutil.rmtree, self.local, ignore_errors=True)
        self.log = self.local / 'Crashy' / 'crashy.log'

    def run_child(self, then='', windowed=True):
        code = CHILD.format(app=str(ROOT / 'app'), windowed=windowed, then=then)
        return subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                              env=dict(os.environ, LOCALAPPDATA=str(self.local)), timeout=60)

    def text(self):
        return self.log.read_text(encoding='utf-8')

    def test_prints_and_tracebacks_land_in_the_log(self):
        self.run_child("print('hello')\nraise ValueError('boom')")
        text = self.text()
        self.assertTrue(text.startswith('--- '), text)
        self.assertIn(f'log at {self.log}', text)
        self.assertIn('hello', text)
        self.assertIn('ValueError: boom', text)

    def test_a_native_crash_leaves_its_stack(self):
        result = self.run_child('def deep():\n    import faulthandler\n    faulthandler._read_null()\ndeep()')
        self.assertNotEqual(result.returncode, 0)
        text = self.text()
        self.assertIn('Windows fatal exception: access violation', text)
        self.assertIn(' in deep', text)

    def test_a_long_log_starts_afresh_and_keeps_one_old_one(self):
        self.log.parent.mkdir(parents=True)
        self.log.write_text('old run\n' * 200_000, encoding='utf-8')
        self.run_child("print('new run')")
        old = self.log.with_suffix('.old.log')
        self.assertTrue(old.read_text(encoding='utf-8').startswith('old run'))
        self.assertNotIn('old run', self.text())
        self.assertIn('new run', self.text())
        self.run_child("print('next run')")          # small now: appended, not rotated again
        self.assertIn('new run', self.text())
        self.assertIn('next run', self.text())

    def test_a_console_run_keeps_its_console(self):
        result = self.run_child("print('hello')", windowed=False)
        self.assertIn('log at None', result.stdout)
        self.assertIn('hello', result.stdout)
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
