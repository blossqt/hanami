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


class _Controlled(unittest.TestCase):
    """A Controller of the test's own, with nothing it would do by itself, and the suite's choices
    in a throwaway registry key."""

    def setUp(self):
        from hanami.ui import suitetheme
        self.suitetheme = suitetheme
        self._key = suitetheme._LOOK_KEY
        suitetheme._LOOK_KEY = r'Software\blossqt\SuiteSettingsTest'
        stand_ins = {'show_window': lambda self: None, 'check_releases': lambda self: None}
        self._originals = {name: getattr(hanami.Controller, name) for name in stand_ins}
        for name, stand_in in stand_ins.items():
            setattr(hanami.Controller, name, stand_in)
        self._dev, hanami.DEV = hanami.DEV, True
        self.controller = hanami.Controller(startup=False)
        self.told = []
        self.controller.tray.showMessage = lambda title, body, icon, ms: self.told.append((title, body))

    def tearDown(self):
        import winreg
        self.controller.hotkeys.clear()
        self.controller._server.close()
        hanami.DEV = self._dev
        for name, original in self._originals.items():
            setattr(hanami.Controller, name, original)
        self.suitetheme._LOOK_KEY = self._key
        self.suitetheme._game_quiet = False
        self.suitetheme._game_callbacks.clear()
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r'Software\blossqt\SuiteSettingsTest')
        except OSError:
            pass


class GameTests(_Controlled):
    """Which window is in front is a stand-in: whatever really is (a game, say) is left out of it."""

    def setUp(self):
        super().setUp()
        from unittest import mock
        self.in_front = False
        self._front = mock.patch.object(self.suitetheme, 'game_in_front', lambda: self.in_front)
        self._front.start()
        self.suitetheme._check_game()

    def tearDown(self):
        self._front.stop()
        super().tearDown()

    def game(self, there: bool) -> None:
        self.in_front = there
        self.suitetheme._check_game()

    def test_notifications_wait_until_the_game_is_left(self):
        icon = hanami.icons.app_icon()
        self.game(True)
        self.controller._notified('Grabbit', 'Clip.mp4', 'Finished')
        self.controller._notified('Keytap', 'Keytap', 'Locked')
        self.assertEqual(self.told, [], 'nothing over the game')
        self.game(False)                                                # the game is left
        self.assertEqual(self.told, [('2 notifications', 'Clip.mp4: Finished\nKeytap: Locked')])
        self.controller._say('Hanami', 'Dropshift 0.2 is out.', icon)
        self.assertEqual(self.told[-1], ('Hanami', 'Dropshift 0.2 is out.'), 'and at once, after')

    def test_one_alone_is_told_as_it_was(self):
        self.game(True)
        self.controller._notified('Grabbit', 'Clip.mp4', 'Finished')
        self.game(False)
        self.assertEqual(self.told, [('Clip.mp4', 'Finished')])

    def test_the_games_page_chooses_for_the_suite(self):
        window = SettingsWindow([], False, (True, True, False))
        window.game_quiet.setChecked(False)
        self.assertFalse(self.suitetheme.game_quiet_chosen())
        self.assertFalse(window.download_buttons['pause'].isEnabled(), 'nothing to choose while it is off')
        window.game_quiet.setChecked(True)
        window.download_buttons['pause'].click()
        self.assertEqual(self.suitetheme.game_downloads(), 'pause')


class SoundTests(_Controlled):
    def setUp(self):
        super().setUp()
        from hanami import audio
        self.audio = audio
        self.outputs = [audio.Output('a', 'Speakers (EDIFIER M230)'), audio.Output('b', 'Headphones (Protocol Max)'),
                        audio.Output('c', 'TYPEC (NVIDIA High Definition Audio)')]
        self.now = 'a'
        from unittest import mock
        self._patches = [mock.patch.object(audio, 'outputs', lambda: list(self.outputs)),
                         mock.patch.object(audio, 'current', lambda: self.now),
                         mock.patch.object(audio, 'choose', self._choose)]
        for patch in self._patches:
            patch.start()

    def _choose(self, output_id):
        self.now = output_id

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        if self.controller.sound_popup is not None:
            self.controller.sound_popup.hide()
        self.controller.settings.set_sound(True, hanami.SOUND_HOTKEY, [])
        super().tearDown()

    def test_the_hotkey_goes_through_the_chosen_outputs(self):
        self.controller.settings.set_sound(True, 'Ctrl+Alt+S', ['a', 'b'])
        self.controller.switch_sound()
        self.assertEqual(self.now, 'b')
        self.assertEqual(self.controller.sound_popup.name, 'Headphones (Protocol Max)', 'and says where')
        self.controller.switch_sound()
        self.assertEqual(self.now, 'a', 'round again, past the one not chosen')

    def test_all_of_them_with_fewer_than_two_chosen(self):
        self.controller.settings.set_sound(True, 'Ctrl+Alt+S', ['b'])
        for expected in ('b', 'c', 'a'):
            self.controller.switch_sound()
            self.assertEqual(self.now, expected)

    def test_with_one_output_there_is_nothing_to_switch_to(self):
        self.outputs = self.outputs[:1]
        self.controller.switch_sound()
        self.assertEqual(self.now, 'a')
        self.assertEqual(self.controller.sound_popup.name, 'There is no other sound output')

    def test_the_sound_page_keeps_what_is_chosen(self):
        self.controller.show_settings('Sound')
        window = self.controller.settings_window
        self.assertEqual(list(window.outputs), ['a', 'b', 'c'])
        window.outputs['b'].setChecked(True)
        window.outputs['c'].setChecked(True)
        self.assertEqual(self.controller.settings.sound_outputs, ['b', 'c'])
        self.outputs = self.outputs[:2]                                  # the TYPEC screen unplugged
        self.controller.show_settings('Sound')
        window.outputs['a'].setChecked(True)
        self.assertEqual(sorted(self.controller.settings.sound_outputs), ['a', 'b', 'c'], 'kept for when it is back')
        window.sound_on.setChecked(False)
        self.assertFalse(self.controller.settings.sound_hotkey_on)
        window.close()

    def test_a_hotkey_that_cant_be_had_says_so(self):
        from hanami.hotkeys import HotkeyError, normalize, parse
        self.assertEqual(normalize('alt+ctrl+s'), 'Ctrl+Alt+S')
        with self.assertRaises(HotkeyError):
            parse('S')
        self.controller.show_settings('Sound')
        self.controller._sound_changed(True, 'S', [])
        self.assertTrue(self.controller.settings_window.sound_problem.text())
        self.assertEqual(self.controller.settings.sound_hotkey, hanami.SOUND_HOTKEY, 'the old one is kept')
        self.controller.settings_window.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
