"""Hanami's start-up, its cherry-blossom tray icon, and the launcher window.

The suite's apps fold their tray menus into Hanami's icon (host.py and each
app's suitelink.py), so the tray holds one icon however many of them run.
Hanami also installs and updates them, from their signed GitHub releases
(releases.py, installer.py).
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QSettings, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import APP_NAME, __version__, catalog, installer, releases, win32
from .host import TrayHost
from .ui import icons, theme
from .ui.launcher import CardState, LauncherWindow

SERVER_NAME = os.environ.get('HANAMI_INSTANCE') or f'hanami-{os.environ.get("USERNAME", "user")}'
APP_ID = 'Suite.Hanami'
DEV = os.environ.get('HANAMI_DEV') == '1'

CHECK_EVERY = 12 * 3600          # how often Hanami asks GitHub for newer releases
CHECK_AGAIN = 15 * 60            # opening the window asks again once this has passed
QUIT_WAIT = 20                   # seconds an app gets to quit before an update


class Settings:
    def __init__(self):
        path = os.environ.get('HANAMI_SETTINGS')
        self._store = QSettings(path, QSettings.IniFormat) if path else QSettings('Hanami', 'Hanami')

    @property
    def start_with(self) -> list[str]:
        try:
            names = json.loads(str(self._store.value('startup/apps', '[]')))
        except ValueError:
            return []
        return [n for n in names if n in catalog.BY_NAME] if isinstance(names, list) else []

    @start_with.setter
    def start_with(self, names: list[str]) -> None:
        self._store.setValue('startup/apps', json.dumps(names))

    def exe(self, name: str) -> Path | None:
        """Where an app is: as set by hand, else where Hanami installed it, else its own build."""
        app = catalog.BY_NAME[name]
        chosen = str(self._store.value(f'apps/{name}/exe', '') or '')
        for candidate in (Path(chosen) if chosen else None, catalog.installed_exe(app), app.dev_build):
            if candidate is not None and candidate.is_file():
                return candidate
        return None

    def set_exe(self, name: str, path: str) -> None:
        self._store.setValue(f'apps/{name}/exe', path)

    def installed(self, name: str) -> dict | None:
        """What Hanami installed: {'version': '1.2.3', 'files': [names in the app's folder]}."""
        try:
            record = json.loads(str(self._store.value(f'apps/{name}/installed', '') or 'null'))
        except ValueError:
            return None
        if not isinstance(record, dict) or not catalog.installed_exe(catalog.BY_NAME[name]).is_file():
            return None
        return record

    def set_installed(self, name: str, version: str | None, files: list[str] | None = None) -> None:
        if version is None:
            self._store.remove(f'apps/{name}/installed')
        else:
            self._store.setValue(f'apps/{name}/installed', json.dumps({'version': version, 'files': files}))

    def told(self, name: str) -> str:
        """The newest release Hanami has already mentioned, so it says so once."""
        return str(self._store.value(f'apps/{name}/told', '') or '')

    def set_told(self, name: str, version: str) -> None:
        self._store.setValue(f'apps/{name}/told', version)

    @property
    def set_up(self) -> bool:
        return str(self._store.value('set_up', 'false')).lower() == 'true'

    @set_up.setter
    def set_up(self, value: bool) -> None:
        self._store.setValue('set_up', 'true' if value else 'false')


class _Job:
    """An install, update or removal under way."""

    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind            # 'install', 'update' or 'uninstall'
        self.phase = 'quit'
        self.done = self.total = 0
        self.cancel = threading.Event()
        self.restart = False        # start the app again afterwards
        self.waited = 0.0


class _Bridge(QObject):
    """Carries results from worker threads back to Qt's."""
    checked = Signal(object)                  # {name: Release or error text}
    progress = Signal(str, str, int, int)     # name, phase, done, total
    finished = Signal(str, object)            # name, files installed (list) or an error (str)


class Controller(QObject):
    def __init__(self, startup: bool):
        super().__init__()
        self.settings = Settings()
        self.host = TrayHost(self)
        self.host.changed.connect(self._changed)
        self.host.notified.connect(self._notified)
        self.window: LauncherWindow | None = None
        self._running: set[str] = set()
        self.latest: dict[str, releases.Release] = {}
        self.problems: dict[str, str] = {}
        self.jobs: dict[str, _Job] = {}
        self._checking = False
        self._checked_at = 0.0
        self._versions: dict[tuple, str] = {}
        self._bridge = _Bridge(self)
        self._bridge.checked.connect(self._releases_checked)
        self._bridge.progress.connect(self._job_progress)
        self._bridge.finished.connect(self._job_finished)
        self._make_tray()
        self._listen()
        self._poll = QTimer(self, interval=2000)
        self._poll.timeout.connect(self._refresh)
        self._poll.start()
        self._checks = QTimer(self, interval=CHECK_EVERY * 1000)
        self._checks.timeout.connect(self.check_releases)
        self._checks.start()
        QTimer.singleShot(1000 if DEV else 8000, self.check_releases)
        self._refresh()
        if startup:
            QTimer.singleShot(2500, self._start_chosen)
        elif not DEV:
            self.show_window()
        if not self.settings.set_up and getattr(sys, 'frozen', False):
            self.settings.set_up = True
            QTimer.singleShot(1000, self._add_to_start_menu)

    # ------------------------------------------------------------------ apps

    def is_running(self, name: str) -> bool:
        return name in self.host.members or name in self._running

    def open_app(self, name: str) -> None:
        """Start an app - or, if it is running, bring it up (each app does that for a second start)."""
        exe = self.settings.exe(name)
        if exe is None:
            self.show_window()
            return
        process = QProcess()
        process.setProgram(str(exe))
        process.setWorkingDirectory(str(exe.parent))
        environment = QProcessEnvironment()
        for key, value in installer.clean_environment().items():
            environment.insert(key, value)
        process.setProcessEnvironment(environment)
        started, _pid = process.startDetached()
        if not started:
            self.tray.showMessage('Hanami', f'{name} would not start.', icons.app_icon(), 5000)
        QTimer.singleShot(1500, self._refresh)

    def quit_app(self, name: str) -> None:
        self.host.click(name, 'quit')
        QTimer.singleShot(1500, self._refresh)

    def _start_chosen(self) -> None:
        self._refresh()
        for name in self.settings.start_with:
            if not self.is_running(name):
                self.open_app(name)

    def _refresh(self) -> None:
        programs = win32.running_programs()
        running = set()
        for app in catalog.SUITE:
            exe = self.settings.exe(app.name)
            if exe is not None and os.path.normcase(str(exe)) in programs:
                running.add(app.name)
        changed = running != self._running
        self._running = running
        if changed:
            self._changed()
        elif self.window is not None and self.window.isVisible():
            self._update_window()

    def _changed(self) -> None:
        self._update_tray()
        self._update_window()

    def _notified(self, app: str, title: str, body: str) -> None:
        member = self.host.members.get(app)
        icon = member.icon if member is not None and not member.icon.isNull() else icons.app_icon()
        self.tray.showMessage(title or app, body, icon, 5000)

    def version_of(self, name: str, exe: Path | None) -> str:
        """The version of the copy on this PC, if it can be told."""
        if exe is None:
            return ''
        record = self.settings.installed(name)
        if record and exe == catalog.installed_exe(catalog.BY_NAME[name]):
            return str(record.get('version') or '')
        try:
            key = (str(exe), exe.stat().st_mtime)
        except OSError:
            return ''
        if key not in self._versions:
            self._versions[key] = installer.exe_version(exe)
        return self._versions[key]

    def update_available(self, name: str) -> bool:
        """A newer release of an app Hanami installed (other copies update themselves, or by hand)."""
        release = self.latest.get(name)
        record = self.settings.installed(name)
        return (release is not None and release.asset is not None and record is not None
                and releases.is_newer(release.version, record.get('version')))

    # ------------------------------------------------------------------ releases

    def check_releases(self) -> None:
        """Ask GitHub, in the background, for each app's newest release."""
        if self._checking:
            return
        self._checking = True
        apps = list(catalog.SUITE) + [catalog.HANAMI]

        def work():
            results = {}
            for app in apps:
                try:
                    results[app.name] = releases.latest(app)
                except releases.ReleaseError as error:
                    results[app.name] = str(error)
                except Exception as error:  # noqa: BLE001 - a bug here must not take Hanami down
                    results[app.name] = f'The check failed: {error}'
            self._bridge.checked.emit(results)

        threading.Thread(target=work, name='hanami-check', daemon=True).start()

    def _releases_checked(self, results: dict) -> None:
        self._checking = False
        self._checked_at = time.monotonic()
        for name, result in results.items():
            if isinstance(result, releases.Release):
                self.latest[name] = result
                self.problems.pop(name, None)
            elif name in catalog.BY_NAME and name not in self.jobs:
                # A failed check only matters for an app that isn't here: one
                # that is keeps working, and is checked again later.
                self.problems[name] = result if self.settings.exe(name) is None else ''
        for app in catalog.SUITE:
            if self.update_available(app.name) and self.settings.told(app.name) != self.latest[app.name].version:
                self.settings.set_told(app.name, self.latest[app.name].version)
                self.tray.showMessage('Hanami', f'{app.name} {self.latest[app.name].version} is out. '
                                      'Open Hanami to update it.', icons.app_icon(), 6000)
        self._update_window()

    def show_page(self, name: str) -> None:
        app = catalog.HANAMI if name == catalog.HANAMI.name else catalog.BY_NAME[name]
        release = self.latest.get(name)
        QDesktopServices.openUrl(QUrl(release.page(app) if release else app.releases_page))

    # ------------------------------------------------------------------ installing

    def install_app(self, name: str) -> None:
        """Install an app, or update the copy Hanami installed, from its newest release."""
        if name in self.jobs:
            return
        kind = 'update' if self.settings.installed(name) else 'install'
        job = self.jobs[name] = _Job(name, kind)
        self.problems.pop(name, None)
        job.restart = kind == 'install' or self._holding(name)
        self._when_quit(job, self._download)

    def uninstall_app(self, name: str, ask: bool = True) -> None:
        if name in self.jobs or not self.settings.installed(name):
            return
        if ask:
            answer = QMessageBox.question(
                self.window, 'Hanami', f'Uninstall {name}?\n\nIts program is removed from this PC; '
                'its settings and anything it saved are left where they are.')
            if answer != QMessageBox.Yes:
                return
        job = self.jobs[name] = _Job(name, 'uninstall')
        self._when_quit(job, self._remove)

    def cancel_install(self, name: str) -> None:
        job = self.jobs.get(name)
        if job is not None:
            job.cancel.set()
            if job.phase == 'quit':
                self._job_finished(name, 'Cancelled.')

    def _holding(self, name: str) -> bool:
        """Is a program running from the app's install folder? Another copy, such as
        a build of it elsewhere, doesn't stand in an install's way."""
        folder = os.path.normcase(str(catalog.install_dir(catalog.BY_NAME[name]))) + os.sep
        return any(path.startswith(folder) for path in win32.running_programs())

    def _when_quit(self, job: _Job, then) -> None:
        """Quit the app if it runs from its folder - Windows won't let its files be replaced - then go on."""
        if job.cancel.is_set() or self.jobs.get(job.name) is not job:
            return
        if not self._holding(job.name):
            then(job)
            return
        if job.waited == 0 and job.name in self.host.members:
            self.host.click(job.name, 'quit')
        elif job.waited == 0:
            self._job_finished(job.name, f'Quit {job.name} first, then try again.')
            return
        if job.waited >= QUIT_WAIT:
            self._job_finished(job.name, f'{job.name} didn’t quit. Quit it, then try again.')
            return
        job.waited += 0.5
        self._update_window()
        QTimer.singleShot(500, lambda: (self._refresh(), self._when_quit(job, then)))

    def _download(self, job: _Job) -> None:
        app = catalog.BY_NAME[job.name]
        record = self.settings.installed(job.name) or {}
        previous = list(record.get('files') or [])
        known = self.latest.get(job.name)
        job.phase = 'download'
        self._update_window()
        last = [None]

        def progress(phase, done, total):
            # Each 64 KB chunk would be a repaint; a tenth of a percent is plenty.
            step = (phase, int(1000 * done / total) if total else 0)
            if step != last[0]:
                last[0] = step
                self._bridge.progress.emit(job.name, phase, done, total)

        def work():
            try:
                release = known or releases.latest(app)
                self.latest[job.name] = release
                files = installer.install(app, release, previous, progress, job.cancel)
                self._bridge.finished.emit(job.name, files)
            except releases.ReleaseError as error:
                self._bridge.finished.emit(job.name, str(error))
            except Exception as error:  # noqa: BLE001 - shown on the card, never an error box
                self._bridge.finished.emit(job.name, f'It didn’t install: {error}')

        threading.Thread(target=work, name=f'hanami-install-{app.name}', daemon=True).start()

    def _remove(self, job: _Job) -> None:
        app = catalog.BY_NAME[job.name]
        files = list((self.settings.installed(job.name) or {}).get('files') or [])
        job.phase = 'remove'
        self._update_window()

        def work():
            try:
                installer.uninstall(app, files)
                self._bridge.finished.emit(job.name, [])
            except releases.ReleaseError as error:
                self._bridge.finished.emit(job.name, str(error))
            except Exception as error:  # noqa: BLE001
                self._bridge.finished.emit(job.name, f'It couldn’t be removed: {error}')

        threading.Thread(target=work, name=f'hanami-remove-{app.name}', daemon=True).start()

    def _job_progress(self, name: str, phase: str, done: int, total: int) -> None:
        job = self.jobs.get(name)
        if job is not None:
            job.phase, job.done, job.total = phase, done, total
            self._update_window()

    def _job_finished(self, name: str, result) -> None:
        job = self.jobs.pop(name, None)
        if job is None:
            return
        if isinstance(result, str):
            self.problems[name] = '' if result == 'Cancelled.' else result
        elif job.kind == 'uninstall':
            self.settings.set_installed(name, None)
            self.problems.pop(name, None)
        else:
            version = self.latest[name].version
            self.settings.set_installed(name, version, result)
            self.settings.set_told(name, version)
            self.problems.pop(name, None)
            self.tray.showMessage('Hanami', f'{name} {version} is installed.' if job.kind == 'install'
                                  else f'{name} is updated to {version}.', icons.app_icon(), 4000)
            if job.restart and not DEV:
                self.open_app(name)
        self._refresh()
        self._changed()

    # ------------------------------------------------------------------ tray

    def _make_tray(self) -> None:
        self.tray = QSystemTrayIcon(icons.app_icon(), self)
        self._menu = QMenu()
        self._menu.aboutToShow.connect(self._update_tray)
        self.tray.setContextMenu(self._menu)
        self.tray.activated.connect(self._tray_clicked)
        self._update_tray()
        self.tray.show()

    def _update_tray(self) -> None:
        menu = self._menu
        menu.clear()
        members = sorted(self.host.members.values(), key=lambda m: catalog.ORDER.get(m.name, 99))
        for member in members:
            sub = menu.addMenu(member.icon, member.name)
            self._fill(sub, member)
        not_running = [app for app in catalog.SUITE
                       if not self.is_running(app.name) and self.settings.exe(app.name) is not None]
        if not_running:
            start = menu.addMenu('Start')
            for app in not_running:
                start.addAction(app.name, lambda n=app.name: self.open_app(n))
        menu.addSeparator()
        opener = menu.addAction(icons.app_icon(), 'Open Hanami', self.show_window)
        font = QFont(opener.font())
        font.setBold(True)
        opener.setFont(font)
        menu.addAction('Quit Hanami', self.quit)
        names = ', '.join(m.name for m in members)
        self.tray.setToolTip(f'Hanami - {names}' if names else 'Hanami')

    def _fill(self, menu: QMenu, member) -> None:
        for item in member.items:
            if item.get('separator'):
                menu.addSeparator()
                continue
            action = QAction(str(item.get('text', '')), menu)
            item_id = item.get('id')
            action.setEnabled(bool(item.get('enabled', True)) and isinstance(item_id, str))
            if item.get('checkable'):
                action.setCheckable(True)
                action.setChecked(bool(item.get('checked')))
            if item.get('default'):
                font = QFont(action.font())
                font.setBold(True)
                action.setFont(font)
            if isinstance(item_id, str):
                action.triggered.connect(lambda _=False, n=member.name, i=item_id: self.host.click(n, i))
            menu.addAction(action)

    def _tray_clicked(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.show_window()

    # ------------------------------------------------------------------ window

    def show_window(self) -> None:
        if self.window is None:
            self.window = LauncherWindow(self.settings.start_with, win32.starts_with_windows())
            self.window.open_app.connect(self.open_app)
            self.window.quit_app.connect(self.quit_app)
            self.window.install_app.connect(self.install_app)
            self.window.cancel_install.connect(self.cancel_install)
            self.window.uninstall_app.connect(self.uninstall_app)
            self.window.show_page.connect(self.show_page)
            self.window.exe_chosen.connect(self._exe_chosen)
            self.window.startup_changed.connect(self._startup_changed)
        self._update_window()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        if self._checked_at and time.monotonic() - self._checked_at > CHECK_AGAIN:
            self.check_releases()

    def card_state(self, name: str) -> CardState:
        exe = self.settings.exe(name)
        release = self.latest.get(name)
        job = self.jobs.get(name)
        return CardState(exe=exe, running=self.is_running(name), in_tray=name in self.host.members,
                         version=self.version_of(name, exe), installed=self.settings.installed(name) is not None,
                         latest=release.version if release and release.asset else '',
                         update=self.update_available(name), problem=self.problems.get(name, ''),
                         busy=job.phase if job else '', done=job.done if job else 0,
                         total=job.total if job else 0)

    def _update_window(self) -> None:
        if self.window is None:
            return
        for app in catalog.SUITE:
            self.window.cards[app.name].show_state(self.card_state(app.name))
        mine = self.latest.get(catalog.HANAMI.name)
        self.window.show_hanami(mine.version if mine and releases.is_newer(mine.version, __version__) else '')

    def _exe_chosen(self, name: str, path: str) -> None:
        self.settings.set_exe(name, path)
        self._refresh()
        self._update_window()

    def _startup_changed(self, on: bool, names: list[str]) -> None:
        self.settings.start_with = names
        if on != win32.starts_with_windows():
            win32.set_start_with_windows(on)

    def _add_to_start_menu(self) -> None:
        """First run: Hanami in the Start menu, and the suite apps that aren't there yet."""
        folder = win32.start_menu()
        wanted = [('Hanami', Path(sys.executable))]
        wanted += [(app.name, self.settings.exe(app.name)) for app in catalog.SUITE]
        for name, exe in wanted:
            link = folder / f'{name}.lnk'
            if exe is not None and not link.exists():
                try:
                    win32.make_shortcut(link, exe)
                except Exception:  # noqa: BLE001 - a missing shortcut is no reason to fail
                    pass

    def quit(self) -> None:
        for job in self.jobs.values():
            job.cancel.set()
        self.host.close()
        self.tray.hide()
        QApplication.quit()

    # ------------------------------------------------------------------ one copy at a time

    def _listen(self) -> None:
        QLocalServer.removeServer(SERVER_NAME)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        self._server.newConnection.connect(self._connection)
        self._server.listen(SERVER_NAME)

    def _connection(self) -> None:
        socket = self._server.nextPendingConnection()
        socket.waitForReadyRead(500)
        words = bytes(socket.readAll()).decode('utf-8', 'replace').split()
        reply = ''
        if not words or words[0] == 'show':
            self.show_window()
        elif words[0] == 'quit':
            QTimer.singleShot(0, self.quit)
        elif DEV and words[0] == 'state':
            reply = json.dumps({
                'members': {m.name: {'items': m.items, 'tooltip': m.tooltip, 'pid': m.pid}
                            for m in self.host.members.values()},
                'listening': self.host.listening, 'running': sorted(self._running),
                'checking': self._checking,
                'latest': {n: r.version for n, r in self.latest.items()},
                'problems': {n: p for n, p in self.problems.items() if p},
                'installed': {a.name: self.settings.installed(a.name) for a in catalog.SUITE
                              if self.settings.installed(a.name)},
                'jobs': {n: j.phase for n, j in self.jobs.items()},
                'cards': {a.name: {k: str(v) for k, v in vars(self.card_state(a.name)).items()}
                          for a in catalog.SUITE}})
        elif DEV and words[0] == 'click' and len(words) >= 3:
            reply = str(self.host.click(' '.join(words[1:-1]), words[-1]))
        elif DEV and words[0] == 'check':
            self.check_releases()
        elif DEV and words[0] == 'install' and len(words) >= 2:
            self.install_app(' '.join(words[1:]))
        elif DEV and words[0] == 'uninstall' and len(words) >= 2:
            self.uninstall_app(' '.join(words[1:]), ask=False)
        elif DEV and words[0] == 'cancel' and len(words) >= 2:
            self.cancel_install(' '.join(words[1:]))
        if reply:
            socket.write(reply.encode('utf-8'))
            socket.waitForBytesWritten(500)
        socket.disconnectFromServer()


def send(message: str, reply: bool = False) -> str | None:
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(400):
        return None
    socket.write(message.encode('utf-8'))
    socket.waitForBytesWritten(500)
    answer = ''
    if reply and socket.waitForReadyRead(3000):
        answer = bytes(socket.readAll()).decode('utf-8', 'replace')
    socket.disconnectFromServer()
    return answer


def _log_to_file() -> None:
    if sys.stderr is not None:
        return
    folder = win32.app_data()
    folder.mkdir(parents=True, exist_ok=True)
    log = open(folder / 'hanami.log', 'a', encoding='utf-8', buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = log


def self_test(argv: list[str]) -> int:
    """Load what a real start loads and answer with the version - the build's check."""
    target = argv[argv.index('--self-test') + 1] if len(argv) > argv.index('--self-test') + 1 else ''
    app = QApplication(argv[:1])
    theme.install(app)
    try:
        icons.render_app_icon(32)
        LauncherWindow([], False).grab()        # painted, never shown
        win32.running_programs()
        releases.verify_and_parse                # the release checks are in the build
        installer.exe_version(Path(sys.executable))
        answer = __version__
    except Exception as error:  # noqa: BLE001 - answered, not raised: no error box on the desktop
        answer = f'FAILED {type(error).__name__}: {error}'
    if target:
        Path(target).write_text(answer, encoding='utf-8')
    else:
        print(answer)
    app.quit()
    return 0 if not answer.startswith('FAILED') else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    _log_to_file()
    if '--self-test' in argv:
        return self_test(argv)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass
    app = QApplication(argv[:1])
    theme.install(app)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(icons.app_icon())

    if '--send' in argv:
        message = argv[argv.index('--send') + 1] if len(argv) > argv.index('--send') + 1 else 'show'
        answer = send(message, reply=True)
        if answer is None:
            print('Hanami is not running', file=sys.stderr)
            return 1
        if answer:
            print(answer)
        return 0
    if send('startup' if '--startup' in argv else 'show') is not None:
        return 0

    controller = Controller(startup='--startup' in argv)
    if not controller.host.listening:
        QMessageBox.warning(None, 'Hanami', 'Hanami could not open its tray link; the apps will keep '
                            'their own icons.')
    app.styleHints().colorSchemeChanged.connect(lambda *_: None)
    return app.exec()
