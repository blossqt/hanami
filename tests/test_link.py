r"""Hanami's tray link, end to end: a stand-in app joins, shows its menu, gets a
click, and folds back in after Hanami restarts.

    %LOCALAPPDATA%\HanamiBuild\venv\Scripts\python.exe tests\test_link.py

Runs a Hanami of its own (HANAMI_PIPE / HANAMI_INSTANCE), so a real one is left
alone. No keyboard or mouse involved.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ['HANAMI_PIPE'] = 'hanami-tray-test'
os.environ['HANAMI_INSTANCE'] = 'hanami-test'
sys.path.insert(0, str(ROOT / 'app'))

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtNetwork import QLocalSocket   # noqa: E402

from hanami.suitelink import SuiteLink        # noqa: E402

MENU = [{'text': 'All quiet', 'enabled': False}, {'separator': True},
        {'id': 'open', 'text': 'Open Testapp', 'default': True},
        {'id': 'pause', 'text': 'Pause', 'checkable': True, 'checked': False},
        {'id': 'quit', 'text': 'Quit Testapp'}]


def wait(check, seconds=10.0, what='it'):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError(f'timed out waiting for {what}')


class LinkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QCoreApplication.instance() or QCoreApplication([])
        cls.folder = Path(tempfile.mkdtemp(prefix='hanami-test-'))

    def start_hanami(self):
        env = dict(os.environ, HANAMI_DEV='1', HANAMI_SETTINGS=str(self.folder / 'settings.ini'))
        process = subprocess.Popen([sys.executable, str(ROOT / 'app' / 'main.py')], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait(lambda: self.state().get('listening'), 15, 'Hanami to start')
        return process

    def send(self, message):
        socket = QLocalSocket()
        socket.connectToServer('hanami-test')
        if not socket.waitForConnected(500):
            return ''
        socket.write(message.encode())
        socket.waitForBytesWritten(500)
        answer = bytes(socket.readAll()).decode() if socket.waitForReadyRead(2000) else ''
        socket.disconnectFromServer()
        return answer

    def state(self):
        answer = self.send('state')
        return json.loads(answer) if answer else {}

    def test_join_click_and_rejoin(self):
        clicks, states = [], []
        link = SuiteLink('Testapp', b'', on_click=clicks.append, on_state=states.append, retry=0.5)
        link.set_menu(MENU, 'Testapp - quiet')
        link.start()
        self.assertFalse(link.notify('nobody', 'is listening'))     # no Hanami yet

        hanami = self.start_hanami()
        try:
            member = wait(lambda: self.state().get('members', {}).get('Testapp'), 10, 'the app to join')
            self.assertEqual(member['items'], MENU)
            self.assertEqual(member['tooltip'], 'Testapp - quiet')
            self.assertEqual(member['pid'], os.getpid())
            self.assertEqual(states, [True])

            self.assertEqual(self.send('click Testapp pause'), 'True')
            wait(lambda: clicks == ['pause'], 5, 'the click to arrive')

            changed = MENU[:3] + [dict(MENU[3], checked=True)] + MENU[4:]
            link.set_menu(changed, 'Testapp - paused')
            wait(lambda: self.state()['members']['Testapp']['items'] == changed, 5, 'the new menu')
            self.assertTrue(link.notify('Done', 'from Testapp'))

            self.send('quit')
            hanami.wait(10)
            wait(lambda: states == [True, False], 5, 'the app to notice Hanami went')
        finally:
            if hanami.poll() is None:
                hanami.kill()

        hanami = self.start_hanami()
        try:
            member = wait(lambda: self.state().get('members', {}).get('Testapp'), 10, 'the app to rejoin')
            self.assertEqual(member['tooltip'], 'Testapp - paused')     # the latest menu came back with it
            link.stop()
            wait(lambda: 'Testapp' not in self.state().get('members', {}), 5, 'the app to leave')
        finally:
            self.send('quit')
            try:
                hanami.wait(10)
            except subprocess.TimeoutExpired:
                hanami.kill()

    def test_two_apps_and_a_stale_copy(self):
        hanami = self.start_hanami()
        try:
            first = SuiteLink('Alpha', retry=0.5)
            first.set_menu([{'id': 'a', 'text': 'A'}])
            first.start()
            second = SuiteLink('Beta', retry=0.5)
            second.set_menu([{'id': 'b', 'text': 'B'}])
            second.start()
            wait(lambda: set(self.state().get('members', {})) == {'Alpha', 'Beta'}, 10, 'both apps')
            # A second Alpha (a restarted copy whose first never said goodbye) takes over.
            again = SuiteLink('Alpha', retry=0.5)
            again.set_menu([{'id': 'a2', 'text': 'A again'}])
            again.start()
            wait(lambda: self.state()['members']['Alpha']['items'] == [{'id': 'a2', 'text': 'A again'}], 10,
                 'the newer Alpha')
            for link in (first, second, again):
                link.stop()
        finally:
            self.send('quit')
            try:
                hanami.wait(10)
            except subprocess.TimeoutExpired:
                hanami.kill()


if __name__ == '__main__':
    unittest.main(verbosity=2)
