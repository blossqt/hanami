r"""Hanami's settings for starting up, and the apps that start with it - offscreen.

    %LOCALAPPDATA%\HanamiBuild\venv\Scripts\python.exe tests\test_settings.py

Hanami runs here under names of its own (its settings file, its local socket,
its tray link), never the real ones, and starts no app: what it would start is
written down instead.
"""

import os
import sys
import tempfile
import time
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


class _Monitors:
    """Stands in for brightness.Monitors: no real monitor is read, nor set, in these tests."""

    def __init__(self, found):
        self.found, self.looked, self.sent = found, 0, []

    def look(self):
        self.looked += 1

    def set(self, key, percent):
        self.sent.append((key, percent))


class _Controlled(unittest.TestCase):
    """A Controller of the test's own, with nothing it would do by itself, and the suite's choices
    in a throwaway registry key."""

    def setUp(self):
        from unittest import mock
        from hanami.ui import suitetheme
        self._monitors = mock.patch.object(hanami.brightness, 'Monitors', _Monitors)
        self._monitors.start()
        self.volume_now, self.volumes_set = None, []        # never the real volume: no output, unless a test says
        self._volume = [mock.patch.object(hanami.audio, 'volume', lambda: self.volume_now),
                        mock.patch.object(hanami.audio, 'set_volume', self.volumes_set.append)]
        for patch in self._volume:
            patch.start()
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
        self._monitors.stop()
        for patch in self._volume:
            patch.stop()
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
    """The speakers and the headphones: chosen in Settings, switched between from the main window
    and with the hotkey. Windows' outputs are stand-ins - the real ones are never changed."""

    def setUp(self):
        super().setUp()
        from unittest import mock
        from hanami import audio
        self.audio = audio
        self.outputs = [audio.Output('nv', 'Speakers (NVIDIA Broadcast)'), audio.Output('hp', 'Headphones (Protocol Max)'),
                        audio.Output('tc', 'TYPEC (NVIDIA High Definition Audio)'),
                        audio.Output('ed', 'Speakers (EDIFIER M230)')]
        self.now = 'ed'
        self._patches = [mock.patch.object(audio, 'outputs', lambda: list(self.outputs)),
                         mock.patch.object(audio, 'current', lambda: self.now),
                         mock.patch.object(audio, 'choose', self._choose)]
        for patch in self._patches:
            patch.start()
        self.controller.show_settings = lambda page='': self.asked_settings.append(page)
        self.asked_settings = []

    def _choose(self, output_id):
        self.now = output_id

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        if self.controller.sound_popup is not None:
            self.controller.sound_popup.hide()
        if self.controller.window is not None:
            self.controller.window.close()
        s = self.controller.settings
        s.set_sound(True, hanami.SOUND_HOTKEY)
        for which in ('speakers', 'headphones'):
            s.set_output(which, '', '')
        s._store.remove('sound/guessed')
        super().tearDown()

    def test_guessed_the_first_time_from_their_names(self):
        chosen = self.controller.outputs_chosen()
        self.assertEqual(chosen, {'speakers': ('ed', 'Speakers (EDIFIER M230)'),
                                  'headphones': ('hp', 'Headphones (Protocol Max)')},
                         'headphones by name; speakers what sound goes to now')
        self.now = 'nv'
        self.assertEqual(self.controller.outputs_chosen()['speakers'][0], 'ed', 'and kept, not guessed again')

    def test_the_hotkey_goes_between_the_two(self):
        self.controller.switch_sound()
        self.assertEqual(self.now, 'hp')
        self.assertEqual(self.controller.sound_popup.name, 'Headphones (Protocol Max)', 'and says where')
        self.controller.switch_sound()
        self.assertEqual(self.now, 'ed', 'back, past the two not chosen')
        self.now = 'tc'                                     # changed elsewhere, to neither
        self.controller.switch_sound()
        self.assertEqual(self.now, 'hp')

    def test_headphones_unplugged(self):
        self.controller.outputs_chosen()
        self.outputs = [o for o in self.outputs if o.id != 'hp']
        self.controller.switch_sound()
        self.assertEqual(self.now, 'ed', 'nothing changed')
        self.assertEqual(self.controller.sound_popup.name, 'Headphones (Protocol Max) isn’t connected')

    def test_the_switch_on_the_main_window(self):
        from hanami.ui.launcher import LauncherWindow
        controller = self.controller
        controller.window = LauncherWindow()
        controller.window.output_clicked.connect(controller.choose_output)
        controller.window.show()
        controller._update_sound()
        toggle = controller.window.sound
        self.assertEqual(toggle.side, 'speakers', 'lit where the sound goes now')
        self.assertIn('Headphones (Protocol Max)', toggle.toolTip())
        toggle.chosen.emit('headphones')                    # clicked
        self.assertEqual((self.now, toggle.side), ('hp', 'headphones'))
        self.assertIsNone(controller.sound_popup, 'no pop-up: the window shows it')
        self.now = 'tc'                                     # changed in Windows' own settings
        controller._refresh()
        self.assertIsNone(toggle.side, 'neither of the two')

    def test_without_headphones_the_switch_asks_for_them(self):
        self.outputs = [o for o in self.outputs if o.id != 'hp']
        self.controller.choose_output('headphones')
        self.assertEqual(self.asked_settings, ['Sound'])
        self.assertEqual(self.now, 'ed')

    def test_chosen_on_the_sound_page(self):
        window = SettingsWindow([], False, (True, True, False), (True, hanami.SOUND_HOTKEY))
        window.output_chosen.connect(self.controller._output_chosen)
        window.show_outputs(self.outputs, self.controller.outputs_chosen())
        speakers = window.output_choices['speakers']
        self.assertEqual(speakers.currentText(), 'Speakers (EDIFIER M230)')
        speakers.setCurrentIndex(speakers.findText('Speakers (NVIDIA Broadcast)'))
        self.assertEqual(self.controller.settings.output('speakers'), ('nv', 'Speakers (NVIDIA Broadcast)'))
        self.outputs = [o for o in self.outputs if o.id != 'hp']        # the headphones unplugged
        window.show_outputs(self.outputs, self.controller.outputs_chosen())
        self.assertEqual(window.output_choices['headphones'].currentText(), 'Headphones (Protocol Max) (not connected)',
                         'still chosen, for when they are back')
        window.output_choices['headphones'].setCurrentIndex(0)
        self.assertIsNone(self.controller.settings.output('headphones'), 'None')
        window.close()

    def test_a_hotkey_that_cant_be_had_says_so(self):
        from hanami.hotkeys import HotkeyError, normalize, parse
        self.assertEqual(normalize('alt+ctrl+s'), 'Ctrl+Alt+S')
        with self.assertRaises(HotkeyError):
            parse('S')
        self.controller.settings_window = SettingsWindow([], False, (True, True, False), (True, hanami.SOUND_HOTKEY))
        self.controller._sound_changed(True, 'S')
        self.assertTrue(self.controller.settings_window.sound_problem.text())
        self.assertEqual(self.controller.settings.sound_hotkey, hanami.SOUND_HOTKEY, 'the old one is kept')
        self.controller.settings_window.close()


class ScreenTextTests(_Controlled):
    """The hotkey that freezes the screen for copying text from it (ui/screentext.py)."""

    def setUp(self):
        super().setUp()
        self.controller.settings.set_text_hotkey(True, hanami.TEXT_HOTKEY)     # as another test may have left it

    def tearDown(self):
        self.controller.settings.set_text_hotkey(True, hanami.TEXT_HOTKEY)
        super().tearDown()

    def test_its_hotkey_and_tray_item(self):
        s = self.controller.settings
        self.assertEqual((s.text_hotkey_on, s.text_hotkey), (True, hanami.TEXT_HOTKEY))
        self.controller.text_problem = ''
        self.controller._update_tray()
        items = [action.text() for action in self.controller._menu.actions()]
        self.assertIn(f'Copy text from the screen	{hanami.TEXT_HOTKEY}', items)

    def test_a_hotkey_that_cant_be_had_says_so(self):
        self.controller.settings_window = SettingsWindow([], False, (True, True, False), (True, hanami.SOUND_HOTKEY),
                                                         text=(True, hanami.TEXT_HOTKEY))
        self.controller._text_changed(True, 'T')
        self.assertTrue(self.controller.settings_window.text_problem.text())
        self.assertEqual(self.controller.settings.text_hotkey, hanami.TEXT_HOTKEY, 'the old one is kept')
        self.controller._text_changed(True, 'alt+ctrl+y')
        self.assertEqual(self.controller.settings.text_hotkey, 'Ctrl+Alt+Y')
        self.controller._text_changed(False, 'Ctrl+Alt+Y')
        self.assertFalse(self.controller.settings.text_hotkey_on)
        items = [action.text() for action in self.controller._menu.actions()]
        self.assertIn('Copy text from the screen', items, 'still in the tray, without a hotkey named')
        self.controller.settings_window.close()

    def test_the_hotkey_opens_and_closes_it(self):
        from unittest import mock
        opened = []
        with mock.patch.object(hanami.suiteocr, 'available', lambda: True),                 mock.patch.object(self.controller.screen_text, 'open', lambda: opened.append(True)):
            self.controller._hotkey('text')
            self.assertEqual(opened, [True])
            self.controller.screen_text.shades = [object()]          # as if it were open
            with mock.patch.object(self.controller.screen_text, 'close',
                                   lambda: setattr(self.controller.screen_text, 'shades', [])):
                self.controller._hotkey('text')
            self.assertFalse(self.controller.screen_text.is_open)

    def test_without_a_reader_it_says_so(self):
        from unittest import mock
        with mock.patch.object(hanami.suiteocr, 'available', lambda: False):
            self.controller.copy_screen_text()
        self.assertEqual(self.told[-1][0], 'Windows can’t read text here')
        self.assertFalse(self.controller.screen_text.is_open)


class InstallProgressTests(_Controlled):
    """An install's progress, as its window shows it. The download and the unpacking are stand-ins
    that report as often as real ones do - every 64 KB chunk, every file - and nothing is fetched or
    put anywhere."""

    def test_shown_sparingly_and_only_on_its_own_card(self):
        # 0.1.31 redrew every card for each tenth of a percent: the window's thread did little else
        # while an app downloaded (1,950 redraws for one install, 4.7 s of 7.4).
        from unittest import mock
        from hanami import releases
        from hanami.ui.launcher import LauncherWindow
        staged = WORK / 'progress' / 'Grabbit.new'
        staged.mkdir(parents=True, exist_ok=True)

        def prepare(app, release, progress, cancel):
            for done in range(1, 2001):
                progress('download', done * 65536, 2000 * 65536)
            for done in range(1, 1001):
                progress('unpack', done, 1000)
            progress('check', 0, 0)
            return staged
        asset = releases.Asset('Grabbit-9.0.0-win64.zip', 2000 * 65536, '0' * 64, 'https://example.invalid/g.zip')
        self.controller.latest['Grabbit'] = releases.Release('Grabbit', '9.0.0', '', '', asset)
        self.controller.window = LauncherWindow()
        shown = {name: 0 for name in self.controller.window.cards}
        for name, card in self.controller.window.cards.items():
            card.show_state = (lambda real, n: lambda state: (shown.__setitem__(n, shown[n] + 1), real(state)))(
                card.show_state, name)
        signals = []
        self.controller._bridge.progress.connect(lambda *a: signals.append(a[1]))
        with mock.patch.object(hanami.installer, 'prepare', prepare), \
                mock.patch.object(hanami.installer, 'finish', lambda app, staged, previous: ['Grabbit.exe']), \
                mock.patch.object(self.suitetheme, 'game_in_front', lambda: False):
            self.suitetheme._check_game()
            self.controller.install_app('Grabbit')
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and 'Grabbit' in self.controller.jobs:
                qt.processEvents()
                time.sleep(0.01)
        self.assertNotIn('Grabbit', self.controller.jobs, 'installed')
        self.assertLessEqual(len(signals), 8, f'a few steps, not one each chunk: {len(signals)} signals')
        self.assertEqual(sorted(set(signals)), ['check', 'download', 'unpack'], 'each step shown')
        others = {name: count for name, count in shown.items() if name != 'Grabbit'}
        # (three as the install goes, and once more as each app's version is read, off the windows' thread)
        self.assertLessEqual(max(others.values()), 4, f'the other cards left alone: {others}')
        self.controller.window.close()
        self.controller.settings.set_installed('Grabbit', None)


class SelfUpdateTests(_Controlled):
    """Hanami updating itself. Nothing is downloaded, started or quit: the new version is a folder
    of the test's own, and starting it and quitting are written down."""

    def setUp(self):
        super().setUp()
        from unittest import mock
        from hanami import releases
        self.home = WORK / 'self' / 'Hanami'
        self.staged = WORK / 'self' / 'Hanami.new'
        self.staged.mkdir(parents=True, exist_ok=True)
        self.state = {'quiet': False}
        self.started, self.quit, self.prepared = [], [], []
        self._patches = [
            mock.patch.object(hanami, 'DEV', False),
            mock.patch.object(hanami.installer, 'own_folder', lambda: self.home),
            mock.patch.object(hanami.installer, 'prepare_self',
                              lambda release, home: self.prepared.append(release.version) or self.staged),
            mock.patch.object(hanami.subprocess, 'Popen', lambda args, **kw: self.started.append(args)),
            mock.patch.object(hanami.theme, 'quiet_now', lambda: self.state['quiet']),
            mock.patch.object(hanami.win32, 'fullscreen_in_front', lambda: False)]
        for patch in self._patches:
            patch.start()
        self.controller.quit = lambda: self.quit.append(1)
        asset = releases.Asset('Hanami-9.9.9-win64.zip', 1, '0' * 64, 'https://example.invalid/x.zip')
        self.controller.latest['Hanami'] = releases.Release('Hanami', '9.9.9', '', '', asset)

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        self.controller.settings._store.remove('updates/hanami')
        super().tearDown()

    def settle(self, until, seconds=5.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not until():
            qt.processEvents()
            time.sleep(0.02)

    def test_put_in_by_itself_while_not_in_use(self):
        self.controller._auto_update()
        self.settle(lambda: self.started)
        self.assertEqual(self.prepared, ['9.9.9'])
        args = self.started[0]
        self.assertEqual(args[:3], [str(self.staged / 'Hanami.exe'), '--finish-update', str(self.home)])
        self.assertEqual(args[3], str(os.getpid()), 'the new version waits for this one')
        self.assertEqual(self.quit, [1], 'and this one quits for it')

    def test_it_waits_while_in_use_and_never_during_a_game(self):
        self.state['quiet'] = True
        self.controller._auto_update()
        self.settle(lambda: self.prepared, 0.5)
        self.assertEqual(self.prepared, [], 'a game in front: not even downloaded')
        self.state['quiet'] = False
        self.controller.panel.show()
        self.controller._auto_update()
        self.settle(lambda: self.prepared and not self.controller._self_update is None and
                    self.controller._staged_self is not None)
        self.assertEqual(self.started, [], 'the panel out: it waits')
        self.assertTrue(self.controller._hand_over_timer.isActive())
        self.controller._auto_update()
        self.assertEqual(self.prepared, ['9.9.9'], 'and isn\'t fetched twice')
        self.controller.panel.hide()
        self.controller._try_hand_over()
        self.assertEqual(len(self.started), 1, 'once it is closed, it goes in')
        self.assertFalse(self.controller._hand_over_timer.isActive())

    def test_turned_off_or_failed_it_waits_to_be_asked(self):
        self.controller._hanami_updates_changed(False)
        self.assertFalse(self.controller.settings.update_hanami, 'kept')
        self.controller._auto_update()
        self.settle(lambda: self.prepared, 0.5)
        self.assertEqual(self.prepared, [])
        self.controller._self_update_failed = '9.9.9'
        self.controller._hanami_updates_changed(True)
        self.controller._auto_update()
        self.settle(lambda: self.prepared, 0.5)
        self.assertEqual(self.prepared, [], 'a version that failed isn\'t tried again by itself')
        self.controller.update_hanami()                         # the window's "update" link
        self.settle(lambda: self.started)
        self.assertEqual(len(self.started), 1, 'asked: at once')

    def test_not_run_from_source(self):
        from unittest import mock
        with mock.patch.object(hanami.installer, 'own_folder', lambda: None):
            self.assertIsNone(self.controller.hanami_update())
        self.controller.latest['Hanami'] = hanami.releases.Release('Hanami', hanami.__version__, '', '', None)
        self.assertIsNone(self.controller.hanami_update(), 'nothing newer')

    def test_the_settings_switch(self):
        window = SettingsWindow([], False, (True, True, False, True), (True, hanami.SOUND_HOTKEY), 'right')
        window.hanami_updates_changed.connect(self.controller._hanami_updates_changed)
        try:
            self.assertTrue(window.hanami_auto.isChecked())
            window.hanami_auto.setChecked(False)
            self.assertFalse(self.controller.settings.update_hanami)
        finally:
            window.close()


class PanelTests(_Controlled):
    """The edge panel. Where the pointer is, and what is in front, are stand-ins."""

    def setUp(self):
        super().setUp()
        from unittest import mock
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication
        from hanami.ui import panel
        self.panel_module, self.QPoint = panel, QPoint
        self.screen = QGuiApplication.primaryScreen().geometry()
        self.point = QPoint(self.screen.center())
        self.full_screen = False
        self._patches = [mock.patch.object(panel, 'pointer', lambda: self.point),
                         mock.patch.object(hanami.win32, 'fullscreen_in_front', lambda: self.full_screen),
                         mock.patch.object(hanami.win32, 'buttons_down', lambda: False),
                         mock.patch.object(self.suitetheme, 'motion_on', lambda: False),
                         mock.patch.object(panel.theme, 'motion_on', lambda: False),      # as the panel calls it
                         mock.patch.object(self.suitetheme, 'game_in_front', lambda: False),
                         # Keytap and Dropshift on this PC, and no other app
                         mock.patch.object(hanami.Settings, 'exe', lambda s, name: Path(sys.executable)
                                           if name in ('Keytap', 'Dropshift') else None)]
        for patch in self._patches:
            patch.start()
        self.suitetheme._check_game()
        self.panel = self.controller.panel
        self.opened = []
        self.controller.open_app = lambda name, startup=False: self.opened.append(name)
        self.controller.choose_output = lambda which, say=False: self.opened.append(which)
        self.panel.open_app.disconnect()
        self.panel.open_app.connect(lambda name: self.controller.open_app(name))
        self.panel.output_clicked.disconnect()
        self.panel.output_clicked.connect(lambda which: self.controller.choose_output(which))
        self.controller.settings.panel_place = self.panel.place = 0.5      # the middle, whatever a test before left
        self.panel.set_edge('right')

    def tearDown(self):
        self.panel.set_edge('')
        self.controller.settings._store.remove('panel/place')
        for patch in self._patches:
            patch.stop()
        super().tearDown()

    def rest_at(self, x, y, seconds):
        """The pointer at (x, y) for a while, the panel looking as it does."""
        self.point = self.QPoint(x, y)
        loop_until = time.monotonic() + seconds
        while time.monotonic() < loop_until:
            self.panel._look()
            qt.processEvents()
            time.sleep(0.02)

    def test_resting_at_the_middle_of_the_edge_brings_it_out(self):
        s = self.screen
        self.rest_at(s.right(), s.center().y(), 0.1)
        self.assertFalse(self.panel.isVisible(), 'not at once: passing by is not resting')
        self.rest_at(s.right(), s.center().y(), 0.4)
        self.assertTrue(self.panel.isVisible())
        g = self.panel.frameGeometry()
        self.assertEqual(g.right(), s.right() - self.panel_module.MARGIN, 'against the edge it came from')
        self.assertIn('Keytap', self.panel.buttons, 'with the apps on this PC')
        self.assertNotIn('Grabbit', self.panel.buttons)
        self.rest_at(s.center().x(), s.center().y(), 0.7)
        self.assertFalse(self.panel.isVisible(), 'and goes once the pointer has left it')

    def test_nothing_watched_over_a_game(self):
        from unittest import mock
        looked = []
        with mock.patch.object(self.panel_module, 'pointer', lambda: looked.append(1) or self.point):
            self.panel._tab_looked = 0.0
            self.full_screen = True
            self.panel._look()
            self.assertEqual(self.panel._watch.interval(), self.panel_module.QUIET_EVERY, 'only now and then')
            self.assertFalse(self.panel.tab.isVisible())
            looked.clear()
            for _ in range(5):
                self.panel._look()
            self.assertEqual(looked, [], 'the pointer is left alone')
            self.full_screen = False
            self.panel._look()
            self.assertEqual(self.panel._watch.interval(), self.panel_module.WATCH_MS, 'watched again once it goes')
            self.assertTrue(self.panel.tab.isVisible())

    def test_near_the_edge_will_do(self):
        s = self.screen
        self.rest_at(s.right() - self.panel_module.NEAR - 20, s.center().y(), 0.5)
        self.assertFalse(self.panel.isVisible(), 'not out in the screen')
        self.rest_at(s.right() - self.panel_module.NEAR + 10, s.center().y() + 100, 0.5)    # past the tab's end
        self.assertTrue(self.panel.isVisible(), 'a little in from the edge, beside the panel')

    def test_not_at_the_ends_of_the_edge_nor_over_anything_full_screen(self):
        s = self.screen
        self.rest_at(s.right(), s.top() + 5, 0.5)
        self.assertFalse(self.panel.isVisible(), 'the top corner is for windows’ own buttons')
        self.full_screen = True
        self.rest_at(s.right(), s.center().y(), 0.5)
        self.assertFalse(self.panel.isVisible())
        self.full_screen = False
        self.panel.set_edge('left')
        self.rest_at(s.right(), s.center().y(), 0.5)
        self.assertFalse(self.panel.isVisible(), 'only the edge chosen')
        self.rest_at(s.left(), s.center().y(), 0.5)
        self.assertTrue(self.panel.isVisible())
        self.assertEqual(self.panel.frameGeometry().left(), s.left() + self.panel_module.MARGIN)

    def test_choosing_in_it(self):
        s = self.screen
        self.rest_at(s.right(), s.center().y(), 0.4)
        self.panel.buttons['Dropshift'].clicked.emit('Dropshift')
        self.assertEqual(self.opened, ['Dropshift'])
        self.assertFalse(self.panel.isVisible(), 'it goes once something is chosen')
        self.rest_at(s.center().x(), s.center().y(), 0.1)
        self.rest_at(s.right(), s.center().y(), 0.4)
        self.panel.sound.chosen.emit('headphones')
        self.assertEqual(self.opened[-1], 'headphones')

    def test_the_tab_shows_where_it_is(self):
        s, tab = self.screen, self.panel.tab
        self.panel._show_tab()
        self.assertTrue(tab.isVisible())
        g = tab.frameGeometry()
        self.assertEqual(g.right(), s.right(), 'at the edge')
        self.assertAlmostEqual(g.center().y(), s.center().y(), delta=2, msg='in the middle, until moved')
        tab.clicked.emit()
        self.assertTrue(self.panel.isVisible(), 'clicked, the panel comes out')
        self.assertFalse(tab.isVisible(), 'and the tab keeps out of its way')
        self.panel.slide_away()
        self.assertTrue(tab.isVisible(), 'back once the panel goes')
        self.full_screen = True
        self.panel._show_tab()
        self.assertFalse(tab.isVisible(), 'not over anything full screen')
        tab.clicked.emit()
        self.assertFalse(self.panel.isVisible())
        self.full_screen = False

    def test_dragging_the_tab_moves_the_panel(self):
        s, tab = self.screen, self.panel.tab
        self.panel._show_tab()
        tab.dragged.emit(s.top() + s.height() // 5)
        tab.dropped.emit()
        self.assertAlmostEqual(self.controller.settings.panel_place, 0.2, delta=0.02, msg='kept')
        self.assertAlmostEqual(tab.frameGeometry().center().y(), s.top() + s.height() // 5, delta=2)
        self.rest_at(s.right(), s.bottom() - 20, 0.5)
        self.assertFalse(self.panel.isVisible(), 'resting at the far end of the edge does nothing')
        self.rest_at(s.right(), s.top() + s.height() // 5, 0.5)
        self.assertTrue(self.panel.isVisible(), 'beside the tab does')
        self.assertLess(self.panel.frameGeometry().center().y(), s.center().y(), 'and it comes out up there')

    def test_dragging_the_panels_handle_moves_it(self):
        s = self.screen
        self.rest_at(s.right(), s.center().y(), 0.4)
        self.panel.handle.dragged.emit(s.bottom())                    # as far down as it goes
        self.rest_at(s.center().x(), s.center().y(), 0.7)
        self.assertTrue(self.panel.isVisible(), 'held out while it is dragged, wherever the pointer is')
        self.assertEqual(self.panel.frameGeometry().bottom(), s.bottom() - self.panel_module.MARGIN, 'all on screen')
        self.panel.handle.dropped.emit()
        self.assertGreater(self.controller.settings.panel_place, 0.5)
        self.rest_at(s.center().x(), s.center().y(), 0.7)
        self.assertFalse(self.panel.isVisible(), 'and goes, once let go and left')

    def test_the_tabs_look_is_chosen_in_settings(self):
        s, tab = self.screen, self.panel.tab
        self.assertEqual(self.controller.settings.panel_tab, self.panel_module.TAB_LOOK, 'as it comes')
        window = SettingsWindow([], False, (True, True, False), (True, hanami.SOUND_HOTKEY), 'right',
                                self.controller.settings.panel_tab)
        window.tab_changed.connect(self.controller._tab_changed)
        try:
            self.panel._show_tab()
            window.tab_sliders['length'].setValue(160)
            window.tab_sliders['thickness'].setValue(9)
            window.tab_sliders['opacity'].setValue(60)
            self.assertEqual(self.controller.settings.panel_tab, (160, 9, 60), 'kept')
            self.assertEqual(tab.height(), 160, 'shown at once')
            self.assertEqual((tab.thickness, tab.opacity), (9, 60))
            g = tab.frameGeometry()
            self.assertEqual(g.right(), s.right(), 'still against the edge')
            self.assertAlmostEqual(g.center().y(), s.center().y(), delta=2, msg='and where it was along it')
            window.panel_on.setChecked(False)
            self.assertFalse(window.tab_sliders['length'].isEnabled(), 'nothing to choose with the panel off')
        finally:
            window.close()
            self.controller._tab_changed(*self.panel_module.TAB_LOOK)
        self.controller.settings._store.setValue('panel/tab_length', 9999)
        self.assertEqual(self.controller.settings.panel_tab[0], self.panel_module.TAB_LIMITS[0][1], 'within limits')
        self.controller.settings.panel_tab = self.panel_module.TAB_LOOK

    def _open(self):
        s = self.screen
        self.rest_at(s.right(), s.center().y(), 0.4)
        self.assertTrue(self.panel.isVisible())

    def _wheel(self, notches: int) -> None:
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        event = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, -120 * notches),
                            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        self.panel.wheelEvent(event)

    def test_the_microphone_button(self):
        from unittest import mock
        state = {'muted': False}
        with mock.patch.object(hanami.audio, 'mic_muted', lambda: state['muted']), \
                mock.patch.object(hanami.audio, 'mute_mic', lambda muted: state.update(muted=muted)):
            self._open()
            qt.processEvents()
            self.assertIs(self.panel.mic.muted, False, 'shown as it is')
            self.panel.mic.clicked.emit()
            self.assertEqual((state['muted'], self.panel.mic.muted), (True, True), 'muted, and shown so')
            self.panel.mic.clicked.emit()
            self.assertEqual((state['muted'], self.panel.mic.muted), (False, False))
            state['muted'] = None
            self.controller._update_mic()
            self.assertIsNone(self.panel.mic.muted, 'none plugged in')

    def test_the_scroll_wheel_turns_the_pages(self):
        from hanami.stats import Stats
        sampled = []
        self.panel.stats_source = lambda: sampled.append(1) or Stats(12.0, (8 * 2 ** 30, 32 * 2 ** 30), 50.0,
                                                                     (2 * 2 ** 30, 12 * 2 ** 30), 60)
        self.panel.pages.go(0)
        self._open()
        pages = self.panel.pages
        self.assertEqual((pages.current, self.panel.dots.current, self.panel.dots.count), (0, 0, 3))
        self._wheel(1)
        self.assertEqual((pages.current, self.panel.dots.current), (1, 1), 'down: the next page')
        self.assertEqual(sampled, [], 'stats sampled only on their own page')
        self._wheel(1)
        self.assertEqual(pages.current, 2)
        self.assertEqual(len(sampled), 1, 'sampled at once')
        self.assertTrue(self.panel._stats.isActive(), 'and once a second from then')
        self.assertEqual(self.panel.stat_rows['vram'].value, '2.0/12 GB')
        self.assertEqual(self.panel.stat_rows['gpu_temp'].value, '60°C')
        self.assertFalse(self.panel.stat_rows['cpu_temp'].isVisibleTo(self.panel),
                         'no processor temperature without Hanami Sensors')
        self.assertEqual(self.panel._stats.interval(), self.panel_module.STATS_QUICK[0],
                         'looked at often at first, while the temperature may be on its way')
        self.panel.stats_source = lambda: Stats(12.0, (8 * 2 ** 30, 32 * 2 ** 30), cpu_temp=71.0)
        self.panel._sample()
        self.assertEqual(self.panel.stat_rows['cpu_temp'].value, '71°C')
        self.assertEqual(self.panel._stats.interval(), self.panel_module.STATS_EVERY, 'there: once a second')
        self._wheel(1)
        self.assertEqual((pages.current, self.panel.dots.current), (0, 0), 'past the last: round to the first')
        self.assertFalse(self.panel._stats.isActive(), 'the stats out of sight: not sampled')
        self._wheel(-1)
        self.assertEqual((pages.current, self.panel.dots.current), (2, 2), 'up from the first: round to the last')
        self.panel.slide_away()
        self.assertFalse(self.panel._stats.isActive(), 'nothing sampled once it has gone')
        self.panel.set_pages(['apps', 'stats'])
        self.assertEqual((self.panel.dots.count, pages.position), (2, 1), 'two pages: the stats still in sight')
        self.panel.set_pages(['pinned'])
        self.assertFalse(self.panel.dots.isVisibleTo(self.panel), 'one page: no dots')
        self.panel.set_pages(list(self.panel_module.PAGES))
        self.panel.pages.go(0)
        self.panel.stats_source = self.controller.sampler.take

    def test_pages_are_chosen_in_settings(self):
        window = SettingsWindow([], False, (True, True, False), (True, hanami.SOUND_HOTKEY), 'right',
                                panel_pages=self.controller.settings.panel_pages)
        window.pages_changed.connect(self.controller._pages_changed)
        try:
            switches = window.page_switches
            switches['stats'].setChecked(False)
            self.assertEqual(self.controller.settings.panel_pages, ['apps', 'pinned'], 'kept')
            self.assertEqual(self.panel.pages.shown, [0, 1])
            switches['apps'].setChecked(False)
            self.assertFalse(switches['pinned'].isEnabled(), 'the last one can’t be turned off')
            self.assertEqual(self.controller.settings.panel_pages, ['pinned'])
        finally:
            window.close()
            self.controller._pages_changed(list(self.panel_module.PAGES))

    def test_shortcuts(self):
        from unittest import mock
        from hanami.ui import pins
        site = pins.for_address('www.Example.com/news')
        self.assertEqual((site.kind, site.target, site.name), ('website', 'https://www.Example.com/news', 'example.com'))
        self.assertIsNone(pins.for_address('not a website'))
        folder = pins.for_path(str(Path(__file__).parent))
        self.assertEqual((folder.kind, folder.name), ('folder', 'tests'))
        program = pins.for_path(sys.executable)
        self.assertEqual((program.kind, program.name), ('file', Path(sys.executable).stem))
        window = SettingsWindow([], False, (True, True, False), (True, hanami.SOUND_HOTKEY), 'right',
                                pinned=self.controller.settings.pinned)
        window.pins_changed.connect(self.controller._pins_changed)
        opened, settings_pages = [], []
        try:
            window.address.setText('example.com')
            window._add_website()
            window._pin(program)
            window._pin(program)
            self.assertEqual(window.pin_note.text(), f'{program.name} is there already.')
            self.assertEqual([p.name for p in self.controller.settings.pinned], ['example.com', program.name], 'kept')
            with mock.patch.object(pins, 'open_pin', lambda pin: opened.append(pin.name) or ''), \
                    mock.patch.object(self.controller, 'show_settings', lambda page='': settings_pages.append(page)):
                self._open()
                self._wheel(1)
                self.assertEqual(len(self.panel.pin_buttons), 3, 'the two, then a plus')
                self.panel.pin_buttons[1].clicked.emit(program.name)
                self.assertEqual(opened, [program.name])
                self.assertFalse(self.panel.isVisible(), 'it goes once something is opened')
                self._open()
                self.panel.pin_buttons[-1].clicked.emit()
                self.assertEqual(settings_pages, ['Edge panel'], 'the plus: to Settings, to add more')
            window._remove_pin(0)
            self.assertEqual([p.name for p in self.controller.settings.pinned], [program.name])
        finally:
            window.close()
            self.controller._pins_changed([])
            self.panel.pages.go(0)

    def test_hanami_sensors_in_settings(self):
        from hanami import sensors
        window = SettingsWindow([], False, (True, True, False), (True, hanami.SOUND_HOTKEY), 'right')
        asked = []
        window.sensors_asked.connect(asked.append)
        try:
            shown = lambda: (window.sensors_status.text(), window.sensors_install.text(),
                             not window.sensors_install.isHidden(), window.sensors_install.isEnabled(),
                             not window.sensors_remove.isHidden())
            window.show_sensors(sensors.State('', '1.0.0', True, True))
            self.assertEqual(shown(), ('Not installed.', 'Install', True, True, False))
            window.sensors_install.click()
            self.assertEqual(asked, ['--install'])
            window.show_sensors(sensors.State('', '1.0.0', True, True), 'Installing…')
            self.assertFalse(window.sensors_install.isEnabled(), 'not twice at once')
            window.show_sensors(sensors.State('1.0.0', '1.0.0', True, True))
            self.assertEqual(shown(), ('Installed.', 'Install', False, True, True))
            window.sensors_remove.click()
            self.assertEqual(asked[-1], '--uninstall')
            window.show_sensors(sensors.State('1.0.0', '1.1.0', True, True))
            self.assertEqual(shown()[1:], ('Update', True, True, True), 'a newer one in this Hanami: Update')
            window.show_sensors(sensors.State('', '1.0.0', False, True))
            self.assertIn('PawnIO', window.sensors_status.text())
            self.assertFalse(window.sensors_install.isEnabled(), 'nothing to read through without PawnIO')
            window.show_sensors(sensors.State('', '1.0.0', True, False))
            self.assertIn('.NET 10', window.sensors_status.text())
            window.show_sensors(sensors.State('', '', True, True), problem='')
            self.assertEqual(window.sensors_status.text(), 'Not in this build of Hanami.')
            window.show_sensors(sensors.State('', '1.0.0', True, True), problem='Its setup failed (9).')
            self.assertFalse(window.sensors_problem.isHidden())
        finally:
            window.close()

    def test_volume(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtTest import QTest
        self.controller._brightness_changed(False)          # the volume alone
        self._open()
        self.assertFalse(self.panel.fold.isVisibleTo(self.panel), 'no output yet: no sliders button')
        self.controller._sound_polled('', None, 53)
        self.assertTrue(self.panel.fold.isVisibleTo(self.panel), 'a sliders button, brightness off or not')
        QTest.mouseClick(self.panel.fold, Qt.LeftButton)
        row, track = self.panel.volume, self.panel.volume._track()
        self.assertTrue(row.isVisibleTo(self.panel))
        self.assertEqual((row.name, row.value), ('Volume', 53))
        y = round(track.center().y())
        QTest.mousePress(row, Qt.LeftButton, Qt.NoModifier, QPoint(round(track.left() + track.width() / 4), y))
        QTest.mouseRelease(row, Qt.LeftButton, Qt.NoModifier, QPoint(round(track.left() + track.width() / 4), y))
        wheel = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                            Qt.NoModifier, Qt.NoScrollPhase, False)
        position = self.panel.pages.position
        qt.sendEvent(row, wheel)
        self.assertEqual(row.value, 27, 'the wheel over it: up a step')
        self.assertEqual(self.panel.pages.position, position, 'and the page stays')
        deadline = time.monotonic() + 3
        while self.volumes_set[-1:] != [27] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.volumes_set[-1:], [27], 'set, on the sound thread')
        self.controller._sound_polled('', None, 60)
        self.assertEqual(row.value, 27, 'a reading from before doesn’t move it back')
        self.controller._sound_polled('', None, None)
        self.assertFalse(self.panel.fold.isVisibleTo(self.panel), 'no output any more: gone')
        self.controller._brightness_changed(True)

    def test_buttons(self):
        from hanami.ui.panel import INNER
        p = self.panel
        self._open()
        self.controller._sound_polled('', None, 53)
        shown =lambda: [w.isVisibleTo(p) for w in (p.fold, p.sound, p.mic)]
        self.assertEqual(shown(), [True, True, True], 'all of them at first')
        tall = p.height()
        window = SettingsWindow([], False, (True, True, False), (True, hanami.SOUND_HOTKEY), 'right')
        window.buttons_changed.connect(self.controller._buttons_changed)
        try:
            window.button_switches['levels'].setChecked(False)
            self.assertEqual(shown(), [False, True, True])
            self.assertLess(p.height(), tall, 'the panel shrinks to what it holds')
            self.assertFalse(window.brightness_switch.isEnabled(), 'brightness is in the drop-down')
            window.button_switches['mic'].setChecked(False)
            self.assertEqual(shown(), [False, True, False])
            self.assertEqual(p.sound.width(), INNER, 'the sound switch takes the mic’s room')
            window.button_switches['output'].setChecked(False)
            self.assertEqual(shown(), [False, False, False])
            self.assertEqual(self.controller.settings.panel_buttons, [], 'kept')
            window.button_switches['mic'].setChecked(True)
            window.button_switches['levels'].setChecked(True)
            self.assertEqual(shown(), [True, False, True])
            self.assertTrue(window.brightness_switch.isEnabled())
            self.assertEqual(self.controller.settings.panel_buttons, ['levels', 'mic'], 'kept, in order')
        finally:
            window.close()
            self.controller._buttons_changed(['levels', 'output', 'mic'])
            self.controller._sound_polled('', None, None)
        self.assertEqual(shown(), [False, True, True])
        self.assertEqual(p.sound.width(), INNER - p.mic.width() - 6, 'back beside the mic')

    def test_brightness(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from hanami.brightness import Monitor
        monitors, s = self.controller.monitors, self.screen
        looked = monitors.looked
        self._open()
        self.assertEqual(monitors.looked, looked + 1, 'looked at again as the panel comes out')
        self.controller._monitors_found([Monitor('a', 'TYPEC', 40), Monitor('b', 'DELL G2524H', 75)])
        rows = self.panel.brightness_rows
        self.assertEqual([(row.name, row.value) for row in rows], [('TYPEC', 40), ('DELL G2524H', 75)])
        self.assertTrue(self.panel.fold.isVisibleTo(self.panel), 'a sliders button')
        self.assertFalse(self.panel.screens.isVisibleTo(self.panel), 'its sliders folded away')
        folded, top = self.panel.height(), self.panel.y()
        QTest.mouseClick(self.panel.fold, Qt.LeftButton)
        self.assertTrue(self.panel.screens_open, 'clicked: they drop down')
        self.assertEqual(self.panel.screens.height(), self.panel._sliders.height())
        self.assertGreater(self.panel.height(), folded + 60, 'the panel grows to hold them')
        self.assertEqual(self.panel.y(), top, 'its top where it was')
        row, track = rows[1], rows[1]._track()
        y = round(track.center().y())
        QTest.mousePress(row, Qt.LeftButton, Qt.NoModifier, QPoint(round(track.left() + track.width() / 4), y))
        QTest.mouseMove(row, QPoint(round(track.center().x()), y))
        self.assertEqual(monitors.sent, [('b', 25), ('b', 50)], 'set as it goes')
        self.controller._monitors_found([Monitor('a', 'TYPEC', 40), Monitor('b', 'DELL G2524H', 75)])
        self.assertEqual(row.value, 50, 'a reading from before doesn’t move it back')
        self.assertIs(self.panel.brightness_rows[1], row, 'the same monitors: the same sliders')
        self.rest_at(s.center().x(), s.center().y(), 0.7)
        self.assertTrue(self.panel.isVisible(), 'dragged past its edge, a slider holds it out')
        QTest.mouseRelease(row, Qt.LeftButton, Qt.NoModifier, QPoint(round(track.center().x()), y))
        self.rest_at(s.center().x(), s.center().y(), 0.7)
        self.assertFalse(self.panel.isVisible(), 'and once let go, it goes')
        self.assertFalse(self.panel.screens_open, 'folded again for next time')
        self.assertFalse(self.panel.screens.isVisibleTo(self.panel))
        self._open()
        QTest.mouseClick(self.panel.fold, Qt.LeftButton)
        QTest.mouseClick(self.panel.fold, Qt.LeftButton)
        self.assertEqual((self.panel.screens_open, self.panel.height()), (False, folded), 'clicked again: folded')
        self.panel.slide_away()
        self.controller._brightness_changed(False)
        self.assertFalse(self.panel.fold.isVisibleTo(self.panel))
        self.assertFalse(self.controller.settings.panel_brightness, 'kept')
        looked = monitors.looked
        self._open()
        self.assertEqual(monitors.looked, looked, 'off: not looked at')
        self.controller._brightness_changed(True)
        self.controller._monitors_found([])
        self.assertFalse(self.panel.fold.isVisibleTo(self.panel), 'no monitor answers, no output: no sliders button')
        window = SettingsWindow([], False, (True, True, False), (True, hanami.SOUND_HOTKEY), 'right')
        window.brightness_changed.connect(self.controller._brightness_changed)
        try:
            window.show_monitors(None)
            self.assertEqual(window.monitors_found.text(), 'Looking for monitors…')
            window.show_monitors(['TYPEC', 'DELL G2524H'])
            self.assertEqual(window.monitors_found.text(), 'Found: TYPEC, DELL G2524H.')
            window.show_monitors([])
            self.assertEqual(window.monitors_found.text(), 'No monitor here answers DDC/CI.')
            window.brightness_switch.setChecked(False)
            self.assertFalse(self.controller.settings.panel_brightness)
            self.assertTrue(window.monitors_found.isHidden())
            window.brightness_switch.setChecked(True)
            window.panel_on.setChecked(False)
            self.assertFalse(window.brightness_switch.isEnabled(), 'nothing to choose with the panel off')
        finally:
            window.close()
            self.controller._brightness_changed(True)

    def test_the_sound_button_asks_for_the_other(self):
        from hanami.ui.sound import SoundToggle
        button, asked = SoundToggle(), []
        button.chosen.connect(asked.append)
        button.show_output('speakers')
        button._other() == 'headphones' and button.chosen.emit(button._other())
        button.show_output('headphones')
        button.chosen.emit(button._other())
        button.show_output(None)
        button.chosen.emit(button._other())
        self.assertEqual(asked, ['headphones', 'speakers', 'headphones'], 'neither: the headphones')

    def test_turned_off_or_moved_in_settings(self):
        window = SettingsWindow([], False, (True, True, False), (True, hanami.SOUND_HOTKEY), 'right')
        window.panel_changed.connect(self.controller._panel_changed)
        window.edge_buttons['left'].click()
        self.assertEqual((self.controller.settings.panel_edge, self.panel.edge), ('left', 'left'))
        window.panel_on.setChecked(False)
        self.assertEqual((self.controller.settings.panel_edge, self.panel.edge), ('', None))
        self.assertFalse(window.edge_buttons['right'].isEnabled())
        window.close()



class WindowThreadTests(_Controlled):
    """Nothing slow on the windows' thread, nothing left behind as things move, and an open tray
    menu left alone - each found by .dev/hunt/hunt_hanami.py in Keytap's folder (2026-10-26)."""

    def _spin(self, seconds: float) -> None:
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            qt.processEvents()
            time.sleep(0.01)

    def test_an_open_tray_menu_is_left_alone(self):
        # Grabbit's tooltip changes every second as it downloads: each change made the menu again,
        # closing it under the pointer.
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QIcon
        from hanami.host import Member
        host, menu = self.controller.host, self.controller._menu
        host.members['Grabbit'] = Member('Grabbit', 1, QIcon(), None, [{'id': 'quit', 'text': 'Quit'}], 'Grabbit')
        host.changed.emit()
        made = []
        real_clear = menu.clear
        menu.clear = lambda: (made.append(1), real_clear())
        try:
            menu.popup(QPoint(300, 300))
            qt.processEvents()
            self.assertTrue(menu.isVisible())
            for speed in range(3):
                host.members['Grabbit'].tooltip = f'Grabbit\n↓ {speed} MB/s'
                host.changed.emit()
            self.assertEqual(made, [], 'a tooltip changing leaves it be')
            host.members['Grabbit'].items = [{'id': 'pause', 'text': 'Pause all'}, {'id': 'quit', 'text': 'Quit'}]
            host.changed.emit()
            self.assertEqual(made, [], 'its items changing too, while it is open')
            menu.hide()
            self._spin(0.1)
            self.assertEqual(made, [1], 'made again once it has closed')
            grabbit = next(a.menu() for a in menu.actions() if a.text() == 'Grabbit')
            self.assertEqual([a.text() for a in grabbit.actions()], ['Pause all', 'Quit'])
        finally:
            menu.clear = real_clear
            del host.members['Grabbit']

    def test_the_hotkey_cleared_with_its_clear_button(self):
        from PySide6.QtGui import QKeySequence
        window = SettingsWindow([], False, (True, True, False), (True, 'Ctrl+Alt+S'))
        said = []
        window.sound_changed.connect(lambda on, hotkey: said.append((on, hotkey)))
        window.sound_key.setKeySequence(QKeySequence('Ctrl+Alt+F12'))
        window.sound_key.editingFinished.emit()
        window.sound_key.clear()                    # what its clear button does
        self.assertEqual(said, [(True, 'Ctrl+Alt+F12'), (True, '')])
        window.close()

    def test_animations_are_let_go_once_they_stop(self):
        from PySide6.QtCore import QEvent, QObject
        from hanami.stats import Stats
        from hanami.ui import panel as panel_module
        if not self.suitetheme.motion_on():
            self.skipTest('animations are off on this PC')
        panel = self.controller.panel
        panel.show()

        def count(widget) -> int:
            qt.sendPostedEvents(None, QEvent.DeferredDelete)
            return len(widget.findChildren(QObject))
        stats = Stats(12.0, (8 * 2 ** 30, 32 * 2 ** 30), 50.0, (2 * 2 ** 30, 12 * 2 ** 30), 60)
        row, button, pages = panel.stat_rows['cpu'], panel.hanami, panel.pages
        before = count(row), count(button), count(pages), count(panel)
        for _ in range(30):
            panel.show_stats(stats)                 # each sample's bar glides
            button.enterEvent(QEvent(QEvent.Enter))
            button.leaveEvent(QEvent(QEvent.Leave))
            pages.go((pages.position + 1) % len(pages.shown))
            panel._fold_to(True)
            panel._fold_to(False)
        self._spin(0.6)                             # all of them done
        after = count(row), count(button), count(pages), count(panel)
        self.assertEqual(after, before, 'each animation deleted once it stopped')
        panel.hide()

    def test_an_update_given_up_frees_the_window_at_once(self):
        # Grabbit's staged 3,000 files took 1.2 s to delete on the windows' thread, frozen meanwhile.
        from unittest import mock
        staged = WORK / 'given-up' / 'Grabbit.new'
        staged.mkdir(parents=True, exist_ok=True)
        deleted = []

        def slow_rmtree(path, ignore_errors=False):
            time.sleep(0.5)
            deleted.append(Path(path))
        job = hanami._Job('Grabbit', 'update')
        job.staged = staged
        self.controller.jobs['Grabbit'] = job
        with mock.patch.object(hanami.shutil, 'rmtree', slow_rmtree):
            started = time.monotonic()
            self.controller._job_finished('Grabbit', 'Cancelled.')
            self.assertLess(time.monotonic() - started, 0.2, 'not waited for')
            self.assertFalse(staged.exists(), 'moved aside at once')
            staged.mkdir()
            (staged / 'Grabbit.exe').write_bytes(b'the next try')    # unpacked again meanwhile
            self._spin(0.8)
        self.assertEqual(len(deleted), 1)
        self.assertTrue(deleted[0].name.startswith('Grabbit.new.gone-'), deleted)
        self.assertTrue((staged / 'Grabbit.exe').exists(), 'the next try left be')
        hanami.installer.sweep(staged.parent)
        self.assertEqual([p.name for p in staged.parent.iterdir()], ['Grabbit.new'], 'and the rest swept away')

    def test_a_silent_connection_doesnt_hold_hanami(self):
        # One that connected and took its time froze the windows for up to half a second.
        import threading
        from PySide6.QtCore import QTimer
        answers = []

        def client():
            with open(rf'\\.\pipe\{hanami.SERVER_NAME}', 'r+b', buffering=0) as pipe:
                time.sleep(0.6)
                pipe.write(b'state')
                answers.append(pipe.read(1 << 16))
        thread = threading.Thread(target=client)
        thread.start()
        ticks = []
        timer = QTimer(interval=50)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start()
        self._spin(0.5)
        timer.stop()
        thread.join(3)
        self._spin(0.2)
        self.assertGreaterEqual(len(ticks), 5, 'the windows went on meanwhile')
        gaps = [b - a for a, b in zip(ticks, ticks[1:])]
        self.assertLess(max(gaps), 0.15, f'never held up: {gaps}')
        self.assertTrue(answers and answers[0].startswith(b'{'), f'and it was answered: {answers}')

    def test_versions_are_read_off_the_windows_thread(self):
        from unittest import mock
        exe = Path(sys.executable)

        def slow_version(path):
            time.sleep(0.4)
            return '7.7.7'
        self.controller._versions.clear()
        with mock.patch.object(hanami.installer, 'exe_version', slow_version), \
                mock.patch.object(hanami.Settings, 'exe', lambda s, name: exe):
            started = time.monotonic()
            self.assertEqual(self.controller.version_of('Grabbit', exe), '', 'not known yet')
            self.assertLess(time.monotonic() - started, 0.1, 'not waited for')
            self._spin(0.7)
            self.assertEqual(self.controller.version_of('Grabbit', exe), '7.7.7', 'known once read')

    def test_where_the_sound_goes_is_asked_off_the_windows_thread(self):
        from unittest import mock
        from hanami.ui.launcher import LauncherWindow
        controller = self.controller
        controller.settings.set_output('speakers', 'sp', 'Speakers')
        controller.settings.set_output('headphones', 'hp', 'Headphones')

        def slow_current():
            time.sleep(0.3)
            return 'hp'
        controller.window = LauncherWindow()
        controller.window.show()
        with mock.patch.object(hanami.audio, 'current', slow_current), \
                mock.patch.object(hanami.audio, 'mic_muted', lambda: False):
            started = time.monotonic()
            controller._poll_tick()
            self.assertLess(time.monotonic() - started, 0.1, 'not waited for')
            self._spin(0.6)
            self.assertEqual(controller.window.sound.side, 'headphones', 'shown once known')
        controller.window.close()

    def test_windows_are_made_ready_soon_after_start(self):
        # Unseen, so the panel's first slide and the window's first opening don't stutter.
        from hanami.ui import pins
        controller = self.controller
        controller.settings.pinned = [pins.for_address('example.com')]
        controller._warm_up()
        self.assertIsNotNone(controller.window)
        self.assertTrue(controller.window.internalWinId() and controller.panel.internalWinId(), 'their own windows made')
        self.assertFalse(controller.window.isVisible() or controller.panel.isVisible(), 'and not shown')
        self.assertIn(('website', 'https://example.com'), controller._pin_icons, 'the pinned icons made')
        controller.settings.pinned = []

    def test_running_programs_are_seen_coming_and_going(self):
        import subprocess
        ping = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'PING.EXE'
        named = os.path.normcase(str(ping))
        process = subprocess.Popen([str(ping), '-n', '2', '127.0.0.1'], stdout=subprocess.DEVNULL,
                                   creationflags=0x08000000)
        time.sleep(0.2)
        self.assertIn(named, hanami.win32.running_programs(), 'seen once started')
        self.assertIn(named, hanami.win32.running_programs(), 'and still, looked at again')
        process.wait(5)
        self.assertNotIn(named, hanami.win32.running_programs(), 'gone once it has')


if __name__ == '__main__':
    unittest.main(verbosity=2)
