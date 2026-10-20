r"""Installing, updating and removing suite apps, from their signed releases.

Each app Hanami installs gets a folder of its own under %LOCALAPPDATA%\Programs
(catalog.programs()), where Windows' own per-user installs go, so no
administrator is needed. Installing and updating are the same steps:

  1. download the release file and check it against the signed manifest
     (releases.py) before anything opens it;
  2. unpack it beside the install as <App>.new - a zip holds one folder,
     <App>\, whose contents are the app; a single-exe release is the exe -
     refusing anything that would land outside it;
  3. check the exe is the version the release promised and that it starts
     (--self-test), so a broken build never replaces one that works;
  4. move what the old version had out of the way, into <App>.old, move the
     new one in, and only then delete the old. A failure part-way puts the
     old version back.

Only what a release put in the folder is ever moved or deleted - Hanami
records those names - so anything else kept there, like a portable Grabbit's
data, stays where it is. The app must not be running: Windows won't let a
running program's files be moved, and Hanami quits it first (app.py).
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import tempfile
import zipfile
from ctypes import wintypes
from pathlib import Path
from typing import Callable

from . import catalog, releases, win32
from .catalog import SuiteApp
from .releases import Release, ReleaseError

WORK = Path(tempfile.gettempdir()) / 'hanami-install'
CREATE_NO_WINDOW = 0x08000000

Progress = Callable[[str, int, int], None]      # (what, done, total)


def clean_environment() -> dict:
    """The environment for an app Hanami starts or checks.

    A frozen app hands its children variables describing its own unpacked
    files; another frozen app that inherits them tries to run from Hanami's.
    So they are dropped, and PyInstaller told to start afresh.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith('_PYI_') and k != '_MEIPASS2'}
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return env


class _FixedFileInfo(ctypes.Structure):
    _fields_ = [(name, wintypes.DWORD) for name in (
        'signature', 'struct_version', 'file_ms', 'file_ls', 'product_ms', 'product_ls',
        'flags_mask', 'flags', 'os', 'type', 'subtype', 'date_ms', 'date_ls')]


def exe_version(path: Path) -> str:
    """The version stamped into an exe (its build/version_info.txt), as X.Y.Z - or '' if none."""
    try:
        api = ctypes.windll.version
    except AttributeError:
        return ''
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, wintypes.LPDWORD]
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                   ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return ''
    buffer = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path), 0, size, buffer):
        return ''
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not api.VerQueryValueW(buffer, '\\', ctypes.byref(pointer), ctypes.byref(length)):
        return ''
    info = ctypes.cast(pointer, ctypes.POINTER(_FixedFileInfo)).contents
    return f'{info.file_ms >> 16}.{info.file_ms & 0xFFFF}.{info.file_ls >> 16}'


# ------------------------------------------------------------------- staging

def _beside(app: SuiteApp, suffix: str) -> Path:
    return catalog.programs() / f'{app.name}{suffix}'


def stage(app: SuiteApp, archive: Path, progress: Progress | None = None) -> Path:
    """Unpack the release beside the install, as <App>.new."""
    staged = _beside(app, '.new')
    shutil.rmtree(staged, ignore_errors=True)
    staged.mkdir(parents=True)
    try:
        if app.single_exe:
            shutil.copyfile(archive, staged / app.exe_name)
            return staged
        with zipfile.ZipFile(archive) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            needed = sum(m.file_size for m in members)
            free = shutil.disk_usage(staged).free
            if free < needed + (200 << 20):
                raise ReleaseError(f'There isn’t enough free space: {app.name} needs {needed / 1e6:.0f} MB '
                                   f'and {free / 1e6:.0f} MB is free.')
            root = staged.resolve()
            for index, member in enumerate(members):
                # The zip holds one folder, <App>\, whose contents become the
                # install. Anything that would land outside it is refused.
                parts = Path(member.filename).parts[1:]
                target = staged.joinpath(*parts).resolve() if parts else None
                if target is None or root not in target.parents:
                    raise ReleaseError(f'{app.name}’s release contains a file it shouldn’t.')
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as source, target.open('wb') as out:
                    shutil.copyfileobj(source, out, 1 << 20)
                if progress:
                    progress('unpack', index + 1, len(members))
    except (zipfile.BadZipFile, OSError) as error:
        shutil.rmtree(staged, ignore_errors=True)
        raise ReleaseError(f'{app.name} could not be unpacked: {error}') from None
    except ReleaseError:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return staged


def check(app: SuiteApp, staged: Path, version: str) -> None:
    """Is the unpacked exe the version promised, and does it start?"""
    exe = staged / app.exe_name
    if not exe.is_file():
        raise ReleaseError(f'{app.name}’s release has no {app.exe_name} in it.')
    stamped = exe_version(exe)
    if stamped and stamped != version:
        raise ReleaseError(f'The release says it is {app.name} {version}, but the program in it is '
                           f'{stamped}. It was not installed.')
    if not app.self_test:
        return
    WORK.mkdir(parents=True, exist_ok=True)
    answer = WORK / f'self-test-{app.exe_name}-{version}.txt'
    answer.unlink(missing_ok=True)
    try:
        subprocess.run([str(exe), '--self-test', str(answer)], cwd=str(WORK), env=clean_environment(),
                       creationflags=CREATE_NO_WINDOW, timeout=120)
        said = answer.read_text(encoding='utf-8').strip() if answer.exists() else ''
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReleaseError(f'{app.name} {version} would not start: {error}') from None
    finally:
        answer.unlink(missing_ok=True)
    # Keytap answers "0.1.0 (Bitwarden CLI …)": the version comes first.
    if said.split(' ', 1)[0] != version:
        raise ReleaseError(f'{app.name} {version} would not start on this PC, so it was not installed.')


# ------------------------------------------------------------------ placing

def place(app: SuiteApp, staged: Path, previous: list[str]) -> list[str]:
    """Swap the staged files in for the old version's. Returns what is now installed."""
    target = catalog.install_dir(app)
    new = sorted(p.name for p in staged.iterdir())
    if not target.exists():
        staged.rename(target)
        return new
    old = _beside(app, '.old')
    shutil.rmtree(old, ignore_errors=True)
    old.mkdir()
    moved_out, moved_in = [], []
    try:
        for name in sorted(set(previous) | set(new)):
            if (target / name).exists():
                (target / name).rename(old / name)
                moved_out.append(name)
        for name in new:
            (staged / name).rename(target / name)
            moved_in.append(name)
    except OSError:
        for name in moved_in:                   # put it all back as it was
            try:
                (target / name).rename(staged / name)
            except OSError:
                pass
        for name in moved_out:
            try:
                (old / name).rename(target / name)
            except OSError:
                pass
        shutil.rmtree(old, ignore_errors=True)
        raise ReleaseError(f'Some of {app.name}’s files are in use. Quit {app.name} and try again.') from None
    shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(staged, ignore_errors=True)
    return new


def prepare(app: SuiteApp, release: Release, progress: Progress | None = None, cancel=None) -> Path:
    """Steps 1-3: download, unpack and check, beside the install - all while the
    old version may still be running. Returns the staged folder."""
    if release.asset is None:
        raise ReleaseError(f'{app.name} {release.version} has no Windows download.')
    catalog.programs().mkdir(parents=True, exist_ok=True)
    archive = releases.download(release.asset, WORK, (lambda d, t: progress('download', d, t)) if progress else None,
                                cancel)
    staged = stage(app, archive, progress)
    try:
        if progress:
            progress('check', 0, 0)
        check(app, staged, release.version)
        if cancel is not None and cancel.is_set():
            raise ReleaseError('Cancelled.')
    except ReleaseError:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    archive.unlink(missing_ok=True)
    return staged


def finish(app: SuiteApp, staged: Path, previous: list[str] | None = None,
           progress: Progress | None = None) -> list[str]:
    """Step 4, once the old version has quit: swap the new one in. Returns what is installed."""
    if progress:
        progress('place', 0, 0)
    try:
        names = place(app, staged, previous or [])
    except ReleaseError:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    add_shortcut(app)
    return names


def install(app: SuiteApp, release: Release, previous: list[str] | None = None,
            progress: Progress | None = None, cancel=None) -> list[str]:
    """Install or update an app from a verified release. Returns the names it put in its folder."""
    return finish(app, prepare(app, release, progress, cancel), previous, progress)


def uninstall(app: SuiteApp, names: list[str]) -> None:
    """Remove what the release put there, and the folder if that leaves it empty."""
    target = catalog.install_dir(app)
    for name in names:
        path = target / name
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        except OSError:
            raise ReleaseError(f'Some of {app.name}’s files are in use. Quit {app.name} and try again.') from None
    try:
        target.rmdir()
    except OSError:
        pass                                    # something of the user's is still in there
    shortcut(app).unlink(missing_ok=True)


# ------------------------------------------------------------------ Start menu

def shortcut(app: SuiteApp) -> Path:
    return win32.start_menu() / f'{app.name}.lnk'


def add_shortcut(app: SuiteApp) -> None:
    try:
        win32.make_shortcut(shortcut(app), catalog.installed_exe(app))
    except Exception:  # noqa: BLE001 - a missing shortcut is no reason to fail an install
        pass
