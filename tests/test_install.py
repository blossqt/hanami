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


def folder(where: Path, files: dict) -> Path:
    """A folder of files (name: bytes), with _internal\ as a folder of its own."""
    shutil.rmtree(where, ignore_errors=True)
    for name, data in files.items():
        (where / name).parent.mkdir(parents=True, exist_ok=True)
        (where / name).write_bytes(data)
    return where


def sleeper(seconds: float) -> subprocess.Popen:
    """A program that quits after a while - the old Hanami, for finish_update to wait for."""
    return subprocess.Popen([sys.executable, '-c', f'import time; time.sleep({seconds})'])


class SelfUpdateTest(unittest.TestCase):
    """Hanami putting a newer version of itself in: the swap the new version makes once the old has
    quit (installer.swap_in, app.finish_update)."""

    def setUp(self):
        self.home = folder(WORK / 'self' / 'Hanami', {'Hanami.exe': b'MZ old', '_internal/old.dll': b'old',
                                                       'notes.txt': b'mine'})
        self.staged = folder(WORK / 'self' / 'Hanami.new', {'Hanami.exe': b'MZ new', '_internal/new.dll': b'new'})

    def tearDown(self):
        shutil.rmtree(WORK / 'self', ignore_errors=True)

    def test_swapped_in_keeping_what_is_not_its_own(self):
        installer.swap_in(self.staged, self.home)
        self.assertEqual((self.home / 'Hanami.exe').read_bytes(), b'MZ new')
        self.assertEqual(sorted(p.name for p in (self.home / '_internal').iterdir()), ['new.dll'], 'the old one gone')
        self.assertEqual((self.home / 'notes.txt').read_bytes(), b'mine', 'what isn\'t Hanami\'s stays')
        self.assertFalse(installer.beside(self.home, '.old').exists())
        self.assertTrue(installer.clear_leftovers(self.home), 'and the next start clears .new away')
        self.assertFalse(self.staged.exists())

    def test_a_file_in_use_leaves_the_old_version_whole(self):
        handle = os.open(self.home / '_internal' / 'old.dll', os.O_RDONLY)     # as a running program holds it
        try:
            with self.assertRaisesRegex(releases.ReleaseError, 'in use'):
                installer.swap_in(self.staged, self.home)
        finally:
            os.close(handle)
        self.assertEqual((self.home / 'Hanami.exe').read_bytes(), b'MZ old')
        self.assertEqual((self.home / '_internal' / 'old.dll').read_bytes(), b'old')
        self.assertFalse(installer.beside(self.home, '.old').exists())

    def finish(self, *extra):
        return subprocess.run([sys.executable, str(ROOT / 'app' / 'main.py'), '--finish-update', str(self.home),
                               *extra, '--no-restart'], env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                              capture_output=True, text=True, timeout=60)

    def test_finished_once_the_old_one_has_quit(self):
        old = sleeper(1.5)
        started = time.monotonic()
        done = self.finish(str(old.pid), '--from', str(self.staged))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIsNotNone(old.poll(), 'not before the old one quit')
        self.assertGreater(time.monotonic() - started, 1.0)
        self.assertEqual((self.home / 'Hanami.exe').read_bytes(), b'MZ new')

    def test_one_that_never_quits_is_left_alone(self):
        from hanami import app as hanami
        old = sleeper(60)
        try:
            quit_wait, hanami.QUIT_WAIT = hanami.QUIT_WAIT, 0.5
            try:
                self.assertFalse(installer.wait_for(old.pid, 0.5))
            finally:
                hanami.QUIT_WAIT = quit_wait
        finally:
            old.kill()
        self.assertTrue(installer.wait_for(old.pid, 5), 'gone: no wait')

    @unittest.skipUnless((BUILT / 'Hanami.exe').exists(), 'needs a build of Hanami in dist\\')
    def test_the_build_updates_itself(self):
        """The real thing, short of starting Hanami: the build released as Hanami (under the test
        key), unpacked and checked beside an old copy's folder, then run from there to finish."""
        from hanami import __version__
        version = installer.exe_version(BUILT / 'Hanami.exe')
        if version != __version__:
            self.skipTest(f'the build is {version}, not {__version__}: build it first')
        mine = SuiteApp('Hanami', '', 'Hanami.exe', WORK / 'x', 'test/self', 'unused')
        publish('test/self', 'Hanami', version, f'Hanami-{version}-win64.zip', zipped(BUILT, 'Hanami'))
        staged = installer.prepare_self(releases.latest(mine), self.home, app=mine)
        self.assertEqual(staged, installer.beside(self.home, '.new'), 'beside its folder')
        old = sleeper(1)
        # Under names of the test's own, offscreen: a build that didn't know --finish-update would
        # start as Hanami, and must never reach the real one (it would bring its window up).
        alone = dict(installer.clean_environment(), HANAMI_INSTANCE='hanami-self-update-test',
                     HANAMI_PIPE='hanami-tray-self-update-test', HANAMI_SETTINGS=str(WORK / 'self.ini'),
                     QT_QPA_PLATFORM='offscreen')
        done = subprocess.run([str(staged / 'Hanami.exe'), '--finish-update', str(self.home), str(old.pid),
                               '--no-restart'], cwd=str(staged), env=alone, timeout=60)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(installer.exe_version(self.home / 'Hanami.exe'), version)
        self.assertTrue((self.home / '_internal').is_dir())
        self.assertFalse((self.home / '_internal' / 'old.dll').exists())
        self.assertEqual((self.home / 'notes.txt').read_bytes(), b'mine')
        self.assertTrue(installer.clear_leftovers(self.home))


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
