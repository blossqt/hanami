r"""Hanami's settings for starting up, and the apps that start with it - offscreen.

    %LOCALAPPDATA%\HanamiBuild\venv\Scripts\python.exe tests\test_settings.py

Hanami runs here under names of its own (its settings file, its local socket,
its tray link), never the real ones, and starts no app: what it would start is
written down instead.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

WORK = Path(tempfile.mkdtemp(prefix='hanami-settings-'))
os.environ.update(QT_QPA_PLATFORM='offscreen', HANAMI_SETTINGS=str(WORK / 'hanami.ini'),
                  HANAMI_INSTANCE='hanami-settings-test', HANAMI_PIPE='hanami-tray-settings-test')
os.environ.pop('HANAMI_DEV', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

qt = QApplication.instance() or QApplication([])

from hanami import app as hanami  # noqa: E402
from hanami.ui.settings import SettingsWindow  # noqa: E402


class StartWithTests(unittest.TestCase):
    def test_the_apps_can_be_chosen_whether_or_not_hanami_starts_at_sign_in(self):
        window = SettingsWindow(['Keytap'], False, (True, True, False))
        changed = []
        window.startup_changed.connect(lambda on, names: changed.append((on, names)))
        self.assertTrue(all(check.isEnabled() for check in window.start_with.values()))
        window.start_with['Dropshift'].setChecked(True)
        self.assertEqual(changed[-1], (False, ['Keytap', 'Dropshift']))

    def test_hanami_opened_by_hand_starts_them_too(self):
        hanami.Settings().start_with = ['Keytap', 'Grabbit']
        started = []
        stand_ins = {'open_app': lambda self, name, startup=False: started.append((name, startup)),
                     'show_window': lambda self: None,
                     'check_releases': lambda self: None,
                     'is_running': lambda self, name: name == 'Grabbit'}
        originals = {name: getattr(hanami.Controller, name) for name in stand_ins}
        dev, hanami.DEV = hanami.DEV, False
        for name, stand_in in stand_ins.items():
            setattr(hanami.Controller, name, stand_in)
        try:
            controller = hanami.Controller(startup=False)              # not at sign-in
            loop = QEventLoop()
            QTimer.singleShot(3500, loop.quit)
            loop.exec()
            self.assertEqual(started, [('Keytap', True)], 'in the background, and one running is left be')
            controller._server.close()
        finally:
            hanami.DEV = dev
            for name, original in originals.items():
                setattr(hanami.Controller, name, original)

    def test_a_card_says_starting_until_the_app_is_up(self):
        from hanami.ui.launcher import AppCard, CardState
        card = AppCard(hanami.catalog.BY_NAME['Dropshift'])
        here = Path(sys.executable)
        card.show_state(CardState(exe=here, starting=True))
        self.assertEqual((card.open.text(), card.open.isEnabled()), ('Starting…', False))
        card.show_state(CardState(exe=here, running=True))
        self.assertEqual((card.open.text(), card.open.isEnabled()), ('Open', True))
        card.show_state(CardState(exe=here))
        self.assertEqual(card.open.text(), 'Start')

    def test_every_chosen_app_is_started_however_qt_answers(self):
        """PySide6 6.11's startDetached answers a bare bool, which Hanami once took for a pair - and
        stopped, with a TypeError, after the first app it started. Nothing is started here: the
        process is a stand-in that writes down what it was asked."""
        settings = hanami.Settings()
        settings.start_with = ['Keytap', 'Dropshift', 'Homework Hub']
        for name in settings.start_with:
            settings.set_exe(name, sys.executable)                     # any file that is there
        asked = []

        class Process:
            answer = True

            def setProgram(self, program):
                self.args = []

            def setArguments(self, args):
                self.args = args

            def setWorkingDirectory(self, folder):
                pass

            def setProcessEnvironment(self, environment):
                pass

            def startDetached(self):
                asked.append(self.args)
                if Process.answer == 'fail' and len(asked) == 1:
                    raise OSError('could not start')
                return Process.answer

        stand_ins = {'show_window': lambda self: None, 'check_releases': lambda self: None,
                     'is_running': lambda self, name: False}
        originals = {name: getattr(hanami.Controller, name) for name in stand_ins}
        real_process = hanami.QProcess
        hanami.QProcess = Process
        for name, stand_in in stand_ins.items():
            setattr(hanami.Controller, name, stand_in)
        dev, hanami.DEV = hanami.DEV, True          # so it starts nothing by itself, later
        try:
            controller = hanami.Controller(startup=False)
            for answer in (True, (True, 4321), 'fail'):
                Process.answer, asked[:] = answer, []
                controller._start_chosen()
                self.assertEqual(asked, [['--startup'], [], ['--no-window']], f'all three, answered {answer!r}')
            Process.answer, asked[:] = True, []
            controller.open_app('Homework Hub')                         # its Open button
            self.assertEqual(asked, [[]], 'opened by hand, it opens its window')
            self.assertTrue(controller.card_state('Dropshift').starting, 'its card says "Starting…"')
            hanami.Controller.is_running = lambda self, name: True             # and now it is up
            controller._refresh()
            self.assertFalse(controller.card_state('Dropshift').starting)
            controller._server.close()
        finally:
            hanami.DEV = dev
            hanami.QProcess = real_process
            for name, original in originals.items():
                setattr(hanami.Controller, name, original)
            settings.start_with = []
            for name in ('Keytap', 'Dropshift', 'Homework Hub'):
                settings.set_exe(name, '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
