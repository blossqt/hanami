r"""The shared Qt tray (suitetray.py) against a Hanami of the test's own.

    %LOCALAPPDATA%\HanamiBuild\venv\Scripts\python.exe tests\test_suitetray.py

Qt's offscreen platform: nothing shows on screen, no tray icon appears.
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
os.environ['HANAMI_PIPE'] = 'hanami-tray-test'
os.environ['HANAMI_INSTANCE'] = 'hanami-test'
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(ROOT / 'app'))

from PySide6.QtNetwork import QLocalSocket    # noqa: E402
from PySide6.QtWidgets import QApplication     # noqa: E402

from hanami.suitetray import SuiteTray          # noqa: E402
from hanami.ui import icons                     # noqa: E402

app = QApplication.instance() or QApplication([])


def pump_until(check, seconds=10.0, what='it'):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        result = check()
        if result:
            return result
        time.sleep(0.03)
    raise AssertionError(f'timed out waiting for {what}')


def send(message):
    socket = QLocalSocket()
    socket.connectToServer('hanami-test')
    if not socket.waitForConnected(500):
        return ''
    socket.write(message.encode())
    socket.waitForBytesWritten(500)
    answer = bytes(socket.readAll()).decode() if socket.waitForReadyRead(2000) else ''
    socket.disconnectFromServer()
    return answer


def state():
    answer = send('state')
    return json.loads(answer) if answer else {}


class SuiteTrayTest(unittest.TestCase):
    def test_folds_in_and_out(self):
        folder = Path(tempfile.mkdtemp(prefix='hanami-tray-'))
        env = dict(os.environ, HANAMI_DEV='1', HANAMI_SETTINGS=str(folder / 'settings.ini'))
        hanami = subprocess.Popen([sys.executable, str(ROOT / 'app' / 'main.py')], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            pump_until(lambda: state().get('listening'), 15, 'Hanami')
            tray = SuiteTray('Trayapp', icons.app_icon())
            clicks, suite = [], []
            tray.clicked.connect(clicks.append)
            tray.in_suite_changed.connect(suite.append)
            items = [{'id': 'go', 'text': 'Go', 'default': True}, {'separator': True},
                     {'id': 'quit', 'text': 'Quit'}]
            tray.set_menu(items, 'Trayapp - ready')
            pump_until(lambda: suite == [True], 10, 'the tray to fold into Hanami')
            pump_until(lambda: tray._settled, 5, 'the tray to settle')
            self.assertFalse(tray._local.isVisible())          # its own icon never showed
            member = pump_until(lambda: state()['members'].get('Trayapp'), 5, 'the menu in Hanami')
            self.assertEqual(member['items'], items)

            # A tooltip that changes every second leaves the menu itself alone.
            menu_before = tray._menu.actions()
            for n in range(3):
                tray.set_menu(items, f'Trayapp - {n} KB/s')
            self.assertEqual(tray._menu.actions(), menu_before)
            pump_until(lambda: state()['members']['Trayapp']['tooltip'] == 'Trayapp - 2 KB/s', 5, 'the tooltip')

            send('click Trayapp go')
            pump_until(lambda: clicks == ['go'], 5, 'the click')
            self.assertTrue(tray.notify('Hello', 'through Hanami'))

            tray.set_shown(False)                                # out of the tray altogether
            pump_until(lambda: 'Trayapp' not in state()['members'], 5, 'the app to leave Hanami')
            self.assertFalse(tray._local.isVisible())
            tray.set_shown(True)
            pump_until(lambda: 'Trayapp' in state()['members'], 10, 'the app to come back')

            send('quit')                                         # Hanami goes: the app's own icon returns
            hanami.wait(10)
            # in, out (hidden), in (shown again), out (Hanami gone)
            pump_until(lambda: suite == [True, False, True, False], 5, 'the tray to notice')
            self.assertTrue(tray._local.isVisible() or not tray._local.isSystemTrayAvailable())
            tray.stop()
        finally:
            if hanami.poll() is None:
                hanami.kill()


if __name__ == '__main__':
    unittest.main(verbosity=2)
