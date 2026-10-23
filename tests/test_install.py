r"""Installing, updating and removing apps from signed releases - against a
stand-in for GitHub on this PC, so nothing is downloaded and nothing real is
touched.

    %LOCALAPPDATA%\HanamiBuild\venv\Scripts\python.exe tests\test_install.py

The releases are signed with a key made for the test. Installs go to a
temporary Programs folder and their shortcuts to a temporary Start menu. One
app is a zip holding Hanami's own build (so its --self-test really runs); the
others are single files that are never started.
"""

import base64
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from hanami import catalog, ed25519, installer, releases   # noqa: E402
from hanami.catalog import SuiteApp                          # noqa: E402

SECRET = ed25519.generate_secret()
KEY = ed25519.public_key(SECRET).hex()
WORK = Path(tempfile.mkdtemp(prefix='hanami-install-'))
SITE = WORK / 'site'
BUILT = ROOT / 'dist' / 'Hanami'


def publish(repo: str, app: str, version: str, name: str, data: bytes, *, signed_by=SECRET,
            claim: dict | None = None) -> None:
    """Put a release where the stand-in GitHub serves it, as release.py would."""
    folder = SITE / repo / 'releases' / 'download' / f'v{version}'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    body = {'schema': 1, 'app': app, 'version': version, 'published_at': '2026-10-19T00:00:00Z',
            'notes': '', 'desktop': {'file': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()},
            'android': None}
    body['desktop'].update(claim or {})
    manifest = (json.dumps(body, indent=2) + '\n').encode()
    signature = base64.b64encode(ed25519.sign(signed_by, manifest))
    latest = SITE / repo / 'releases' / 'latest' / 'download'
    latest.mkdir(parents=True, exist_ok=True)
    for where in (folder, latest):                  # in the release, and at the "latest release" address
        (where / 'latest.json').write_bytes(manifest)
        (where / 'latest.json.sig').write_bytes(signature)


def zipped(folder: Path, root: str, extra: dict | None = None) -> bytes:
    path = WORK / f'{root}.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for item in sorted(folder.rglob('*')):
            if item.is_file():
                zf.write(item, f'{root}/{item.relative_to(folder).as_posix()}')
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return path.read_bytes()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve() -> str:
    SITE.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(SITE)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f'http://127.0.0.1:{server.server_address[1]}'


os.environ.update(HANAMI_RELEASE_SITE=serve(), HANAMI_RELEASE_KEY=KEY,
                  HANAMI_PROGRAMS=str(WORK / 'Programs'), HANAMI_START_MENU=str(WORK / 'Start Menu'))
(WORK / 'Start Menu').mkdir()

NOTE = SuiteApp('Note', 'A one-file app that is never started.', 'Note.exe', WORK / 'nowhere.exe',
                'test/note', 'unused', single_exe=True, self_test=False)
BLOSSOM = SuiteApp('Blossom', 'Hanami\'s own build, under another name.', 'Hanami.exe', WORK / 'nowhere.exe',
                   'test/blossom', 'unused')


class ReleaseTest(unittest.TestCase):
    def test_a_release_is_read_and_believed(self):
        publish('test/note', 'Note', '1.0.0', 'Note.exe', b'MZ one')
        release = releases.latest(NOTE)
        self.assertEqual((release.version, release.asset.name, release.asset.size), ('1.0.0', 'Note.exe', 6))
        self.assertTrue(release.asset.url.endswith('/test/note/releases/download/v1.0.0/Note.exe'))

    def test_a_release_signed_by_anyone_else_is_refused(self):
        publish('test/forged', 'Forged', '1.0.0', 'Forged.exe', b'MZ', signed_by=ed25519.generate_secret())
        forged = SuiteApp('Forged', '', 'Forged.exe', WORK / 'x', 'test/forged', 'unused', single_exe=True)
        with self.assertRaisesRegex(releases.ReleaseError, 'signature does not match'):
            releases.latest(forged)

    def test_a_release_of_another_app_is_refused(self):
        publish('test/other', 'SomethingElse', '1.0.0', 'Other.exe', b'MZ')
        other = SuiteApp('Other', '', 'Other.exe', WORK / 'x', 'test/other', 'unused', single_exe=True)
        with self.assertRaisesRegex(releases.ReleaseError, 'different app'):
            releases.latest(other)

    def test_a_stale_cache_of_the_latest_release_is_no_forgery(self):
        """GitHub caches the "latest release" files apart: just after a release, the manifest can
        still be the last release's while the signature is already the new one's."""
        cached = SuiteApp('Cached', '', 'Cached.exe', WORK / 'x', 'test/cached', 'unused', single_exe=True)
        publish('test/cached', 'Cached', '1.0.0', 'Cached.exe', b'MZ one')
        last = (SITE / 'test/cached/releases/latest/download/latest.json').read_bytes()
        publish('test/cached', 'Cached', '1.1.0', 'Cached.exe', b'MZ two')
        self.assertEqual(releases.latest(cached).version, '1.1.0')
        (SITE / 'test/cached/releases/latest/download/latest.json').write_bytes(last)
        self.assertEqual(releases.latest(cached).version, '1.0.0', 'the last release, believed until the cache catches up')

    def test_an_app_without_releases_says_so(self):
        missing = SuiteApp('Missing', '', 'Missing.exe', WORK / 'x', 'test/missing', 'unused')
        with self.assertRaisesRegex(releases.ReleaseError, 'no release yet'):
            releases.latest(missing)

    def test_the_real_key_is_used_unless_a_test_site_is_set(self):
        site = os.environ.pop('HANAMI_RELEASE_SITE')
        try:
            self.assertEqual(releases.public_key(NOTE), 'unused')
            self.assertEqual(releases.site(NOTE), 'https://github.com/test/note')
        finally:
            os.environ['HANAMI_RELEASE_SITE'] = site


class InstallTest(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(WORK / 'Programs', ignore_errors=True)

    def test_install_update_and_remove_keep_what_is_not_theirs(self):
        publish('test/note', 'Note', '1.0.0', 'Note.exe', b'MZ one')
        steps = []
        files = installer.install(NOTE, releases.latest(NOTE), progress=lambda *a: steps.append(a[0]))
        exe = catalog.installed_exe(NOTE)
        self.assertEqual((files, exe.read_bytes()), (['Note.exe'], b'MZ one'))
        self.assertEqual([s for i, s in enumerate(steps) if s not in steps[:i]], ['download', 'check', 'place'])
        self.assertTrue((WORK / 'Start Menu' / 'Note.lnk').exists(), 'a Start menu shortcut')

        (exe.parent / 'my notes.txt').write_text('mine')       # something of the user's, beside it
        publish('test/note', 'Note', '1.1.0', 'Note.exe', b'MZ two')
        files = installer.install(NOTE, releases.latest(NOTE), files)
        self.assertEqual(exe.read_bytes(), b'MZ two')
        self.assertEqual((exe.parent / 'my notes.txt').read_text(), 'mine')
        self.assertEqual(sorted(p.name for p in (WORK / 'Programs').iterdir()), ['Note'], 'nothing left over')

        installer.uninstall(NOTE, files)
        self.assertFalse(exe.exists())
        self.assertTrue((exe.parent / 'my notes.txt').exists(), 'the user\'s file stays')
        self.assertFalse((WORK / 'Start Menu' / 'Note.lnk').exists())

    def test_a_download_that_is_not_the_release_is_not_installed(self):
        publish('test/note', 'Note', '1.0.0', 'Note.exe', b'MZ one', claim={'sha256': '0' * 64})
        with self.assertRaisesRegex(releases.ReleaseError, 'didn’t match'):
            installer.install(NOTE, releases.latest(NOTE))
        self.assertFalse(catalog.install_dir(NOTE).exists())

    def test_files_in_use_leave_the_old_version_whole(self):
        publish('test/note', 'Note', '1.0.0', 'Note.exe', b'MZ one')
        files = installer.install(NOTE, releases.latest(NOTE))
        publish('test/note', 'Note', '1.2.0', 'Note.exe', b'MZ three')
        exe = catalog.installed_exe(NOTE)
        handle = os.open(exe, os.O_RDONLY)           # as Windows holds a running program's exe
        try:
            with self.assertRaisesRegex(releases.ReleaseError, 'in use'):
                installer.install(NOTE, releases.latest(NOTE), files)
        finally:
            os.close(handle)
        self.assertEqual(exe.read_bytes(), b'MZ one')
        self.assertEqual(sorted(p.name for p in (WORK / 'Programs').iterdir()), ['Note'])

    def test_a_zip_reaching_outside_its_folder_is_refused(self):
        folder = WORK / 'evil'
        folder.mkdir(exist_ok=True)
        (folder / 'Evil.exe').write_bytes(b'MZ')
        publish('test/evil', 'Evil', '1.0.0', 'Evil-1.0.0-win64.zip',
                zipped(folder, 'Evil', {'Evil/../../escaped.txt': 'out'}))
        evil = SuiteApp('Evil', '', 'Evil.exe', WORK / 'x', 'test/evil', 'unused', self_test=False)
        with self.assertRaisesRegex(releases.ReleaseError, 'shouldn’t'):
            installer.install(evil, releases.latest(evil))
        self.assertFalse((WORK / 'escaped.txt').exists())
        self.assertFalse((WORK / 'Programs' / 'escaped.txt').exists())

    @unittest.skipUnless((BUILT / 'Hanami.exe').exists(), 'needs a build of Hanami in dist\\')
    def test_a_zipped_app_is_unpacked_and_must_start(self):
        version = installer.exe_version(BUILT / 'Hanami.exe')
        publish('test/blossom', 'Blossom', version, f'Blossom-{version}-win64.zip', zipped(BUILT, 'Blossom'))
        files = installer.install(BLOSSOM, releases.latest(BLOSSOM))
        self.assertIn('Hanami.exe', files)
        self.assertIn('_internal', files)
        self.assertTrue(catalog.installed_exe(BLOSSOM).exists())
        # The same build claiming to be another version is refused before it replaces anything.
        publish('test/blossom', 'Blossom', '9.9.9', 'Blossom-9.9.9-win64.zip', zipped(BUILT, 'Blossom'))
        with self.assertRaisesRegex(releases.ReleaseError, 'program in it is'):
            installer.install(BLOSSOM, releases.latest(BLOSSOM), files)
        self.assertEqual(installer.exe_version(catalog.installed_exe(BLOSSOM)), version)
        self.assertFalse((WORK / 'Programs' / 'Blossom.new').exists())


class ControllerTest(unittest.TestCase):
    """Hanami itself, from source and offscreen, installing Homework Hub from the stand-in site."""

    def ask(self, message: str) -> str:
        from PySide6.QtNetwork import QLocalSocket
        socket = QLocalSocket()
        socket.connectToServer('hanami-install-test')
        if not socket.waitForConnected(500):
            return ''
        socket.write(message.encode())
        socket.waitForBytesWritten(500)
        answer = bytes(socket.readAll()).decode() if socket.waitForReadyRead(3000) else ''
        socket.disconnectFromServer()
        return answer

    def state(self) -> dict:
        answer = self.ask('state')
        return json.loads(answer) if answer else {}

    def wait(self, check, seconds=30.0, what='it'):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = check(self.state())
            if result:
                return result
            time.sleep(0.2)
        self.fail(f'timed out waiting for {what}: {self.state()}')

    def test_install_check_update_uninstall(self):
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.instance() or QCoreApplication([])
        publish('blossqt/homework-hub-releases', 'HomeworkHub', '1.0.0', 'HomeworkHub.exe', b'MZ hub one')
        env = dict(os.environ, HANAMI_DEV='1', HANAMI_INSTANCE='hanami-install-test',
                   HANAMI_PIPE='hanami-tray-install-test', QT_QPA_PLATFORM='offscreen',
                   HANAMI_SETTINGS=str(WORK / 'hanami.ini'))
        hanami = subprocess.Popen([sys.executable, str(ROOT / 'app' / 'main.py')], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        exe = WORK / 'Programs' / 'Homework Hub' / 'HomeworkHub.exe'
        try:
            self.wait(lambda s: s.get('latest', {}).get('Homework Hub') == '1.0.0', 30, 'the first check')
            self.assertIn('Keytap', self.state()['problems'] if not catalog.BY_NAME['Keytap'].dev_build.exists()
                          else {'Keytap': ''})
            self.ask('install Homework Hub')
            self.wait(lambda s: (s.get('installed', {}).get('Homework Hub') or {}).get('version') == '1.0.0',
                      30, 'the install')
            self.assertEqual(exe.read_bytes(), b'MZ hub one')
            card = self.state()['cards']['Homework Hub']
            self.assertEqual((card['installed'], card['version'], card['update']), ('True', '1.0.0', 'False'))

            publish('blossqt/homework-hub-releases', 'HomeworkHub', '1.1.0', 'HomeworkHub.exe', b'MZ hub two')
            self.ask('check')
            self.wait(lambda s: s['cards']['Homework Hub']['update'] == 'True', 30, 'the update to show')
            self.ask('install Homework Hub')
            self.wait(lambda s: (s.get('installed', {}).get('Homework Hub') or {}).get('version') == '1.1.0',
                      30, 'the update')
            self.assertEqual(exe.read_bytes(), b'MZ hub two')
            self.assertEqual(self.state()['cards']['Homework Hub']['update'], 'False')

            self.ask('uninstall Homework Hub')
            self.wait(lambda s: 'Homework Hub' not in s.get('installed', {}) and not s['jobs'], 30, 'the removal')
            self.assertFalse(exe.exists())
        finally:
            self.ask('quit')
            try:
                hanami.wait(10)
            except subprocess.TimeoutExpired:
                hanami.kill()


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
