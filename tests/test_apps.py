r"""Keytap and Dropshift, from source, folding into a Hanami of the test's own.

    %LOCALAPPDATA%\HanamiBuild\venv\Scripts\python.exe tests\test_apps.py

Offscreen (nothing on screen), on a test pipe, with test instance names, so
real copies of the apps and of Hanami are left alone. Keytap runs on a fake
vault. Each app runs in its own build venv.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = Path.home() / 'Documents'
LOCAL = Path(os.environ['LOCALAPPDATA'])
BASE = dict(os.environ, HANAMI_PIPE='hanami-tray-test', QT_QPA_PLATFORM='offscreen')
sys.path.insert(0, str(ROOT / 'app'))

from PySide6.QtCore import QCoreApplication   # noqa: E402
from PySide6.QtNetwork import QLocalSocket    # noqa: E402

QCoreApplication.instance() or QCoreApplication([])


def ask(server, message):
    socket = QLocalSocket()
    socket.connectToServer(server)
    if not socket.waitForConnected(500):
        return ''
    socket.write(message.encode())
    socket.waitForBytesWritten(500)
    answer = bytes(socket.readAll()).decode() if socket.waitForReadyRead(2000) else ''
    socket.disconnectFromServer()
    return answer


def wait(check, seconds=15.0, what='it'):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError(f'timed out waiting for {what}')


def hanami_state():
    answer = ask('hanami-test', 'state')
    return json.loads(answer) if answer else {}


def menu_item(app, item_id):
    member = hanami_state().get('members', {}).get(app) or {}
    return next((i for i in member.get('items', []) if i.get('id') == item_id), None)


class AppsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp(prefix='hanami-apps-'))
        env = dict(BASE, HANAMI_DEV='1', HANAMI_INSTANCE='hanami-test',
                   HANAMI_SETTINGS=str(cls.folder / 'hanami.ini'))
        cls.hanami = subprocess.Popen([sys.executable, str(ROOT / 'app' / 'main.py')], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait(lambda: hanami_state().get('listening'), 15, 'Hanami')

    @classmethod
    def tearDownClass(cls):
        ask('hanami-test', 'quit')
        try:
            cls.hanami.wait(10)
        except subprocess.TimeoutExpired:
            cls.hanami.kill()

    def run_app(self, venv, main, env):
        return subprocess.Popen([str(LOCAL / venv / 'venv' / 'Scripts' / 'python.exe'), str(main)],
                                env=dict(BASE, **env), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def keytap_env(self, name, settings_text):
        vault = self.folder / f'{name}-vault.json'
        vault.write_text(json.dumps({'email': 'test@example.com', 'password': 'x', 'signed_in': True,
                                     'items': []}))
        settings = self.folder / f'{name}.ini'
        settings.write_text('[hotkeys]\ntype=Ctrl+Alt+Shift+F11\npick=Ctrl+Alt+Shift+F12\n' + settings_text)
        return {'KEYTAP_DEV': '1', 'KEYTAP_INSTANCE': name, 'KEYTAP_SETTINGS': str(settings),
                'KEYTAP_BW': str(DOCUMENTS / 'Keytap' / 'tests' / 'fake_bw.py'),
                'KEYTAP_FAKE_VAULT': str(vault), 'KEYTAP_FAKE_DELAY': '0',
                'KEYTAP_BW_DATA': str(self.folder / f'{name}-bw')}

    def test_keytap(self):
        keytap = self.run_app('KeytapBuild', DOCUMENTS / 'Keytap' / 'app' / 'main.py',
                              self.keytap_env('keytap-test', ''))
        try:
            wait(lambda: (menu_item('Keytap', 'lock') or {}).get('text') == 'Unlock…', 20,
                 'the Keytap menu in Hanami, showing it locked')
            self.assertEqual(menu_item('Keytap', 'inline')['checked'], True)
            ask('hanami-test', 'click Keytap inline')        # turn the pop-up off from Hanami's menu
            wait(lambda: menu_item('Keytap', 'inline')['checked'] is False, 5, 'the pop-up switch')
            self.assertFalse(json.loads(ask('keytap-test', 'state'))['watching'])
            ask('hanami-test', 'click Keytap quit')
            keytap.wait(15)
            wait(lambda: 'Keytap' not in hanami_state()['members'], 5, 'Keytap to leave')
        finally:
            if keytap.poll() is None:
                keytap.kill()

    def test_keytap_out_of_the_tray(self):
        keytap = self.run_app('KeytapBuild', DOCUMENTS / 'Keytap' / 'app' / 'main.py',
                              self.keytap_env('keytap-test-2', '[tray]\nshown=false\n'))
        try:
            wait(lambda: json.loads(ask('keytap-test-2', 'state') or '{}').get('state') == 'locked', 20,
                 'Keytap to start')
            time.sleep(1.5)
            self.assertNotIn('Keytap', hanami_state()['members'])
            ask('keytap-test-2', 'quit')
            keytap.wait(15)
        finally:
            if keytap.poll() is None:
                keytap.kill()

    def test_dropshift(self):
        env = {'DROPSHIFT_DEV': '1', 'DROPSHIFT_INSTANCE': 'dropshift-test'}
        dropshift = self.run_app('DropshiftBuild', DOCUMENTS / 'Dropshift' / 'app' / 'main.py', env)
        try:
            wait(lambda: menu_item('Dropshift', 'pause'), 20, 'the Dropshift menu in Hanami')
            ask('hanami-test', 'click Dropshift pause')
            wait(lambda: menu_item('Dropshift', 'pause')['checked'] is True, 5, 'pause to show as on')
            self.assertEqual(ask('dropshift-test', 'paused'), 'True')
            ask('hanami-test', 'click Dropshift quit')
            dropshift.wait(15)
        finally:
            if dropshift.poll() is None:
                dropshift.kill()


if __name__ == '__main__':
    unittest.main(verbosity=2)
