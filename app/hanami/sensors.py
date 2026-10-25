"""Hanami Sensors: the processor's temperature, for the edge panel's stats page.

Windows gives no program the processor's temperature on PCs like this one: it takes a driver to
read. Hanami Sensors - a small service of Hanami's own (sensors\\service, in C#) - reads it through
PawnIO, the driver FanControl and LibreHardwareMonitor use, with LibreHardwareMonitor's library, and
lays it in shared memory (MEMORY) that signed-in users may read but not write. Nothing listens: no
port, no pipe.

Hanami (Reader) asks for a reading by setting an event (WANTED) while the stats page is in sight,
reads the memory, and - when the readings have gone stale, as they do once the service has stopped
itself after a minute unasked - starts the service again: signed-in users may start it and see
whether it runs, nothing more. Its setup (sensors\\HanamiSensorsSetup.exe) installs it into Program
Files - checking every file against hashes built into itself - and is run with administrator
permission from Settings > Edge panel (run_setup).
"""

from __future__ import annotations

import ctypes
import os
import struct
import sys
import threading
import time
import winreg
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

SERVICE = 'HanamiSensors'
MEMORY = r'Global\HanamiSensors'
WANTED = r'Global\HanamiSensorsWanted'
MAGIC, LAYOUT, SIZE = 0x4E534E48, 1, 160
FRESH = 5.0             # s a reading counts for
STALE = 3.0             # s without a newer one before the service is started again
START_AGAIN = 15.0      # s between tries at starting it
INSTALLED = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Hanami Sensors' / 'HanamiSensors.exe'
SETUP_ANSWERS = {
    0: '', 2: 'It needs administrator permission.', 3: 'Its files aren’t as they were built: reinstall Hanami.',
    4: 'The old one wouldn’t stop: restart Windows and try again.', 5: 'Its files couldn’t be copied.',
    6: 'Windows wouldn’t register the service.',
}

_FILE_MAP_READ, _EVENT_MODIFY_STATE = 0x0004, 0x0002
_SC_MANAGER_CONNECT, _SERVICE_QUERY_STATUS, _SERVICE_START = 0x0001, 0x0004, 0x0010
_ERROR_SERVICE_ALREADY_RUNNING, _ERROR_SERVICE_DOES_NOT_EXIST, _ERROR_CANCELLED = 1056, 1060, 1223
_STATES = {1: 'stopped', 2: 'starting', 3: 'stopping', 4: 'running', 5: 'continuing', 6: 'pausing', 7: 'paused'}


def _calls():
    kernel, advapi, shell = ctypes.WinDLL('kernel32', use_last_error=True), \
        ctypes.WinDLL('advapi32', use_last_error=True), ctypes.WinDLL('shell32', use_last_error=True)
    kernel.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenFileMappingW.restype = wintypes.HANDLE
    kernel.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    kernel.MapViewOfFile.restype = ctypes.c_void_p
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    advapi.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    advapi.OpenSCManagerW.restype = wintypes.HANDLE
    advapi.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    advapi.OpenServiceW.restype = wintypes.HANDLE
    advapi.StartServiceW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
    advapi.QueryServiceStatus.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    advapi.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    shell.ShellExecuteExW.argtypes = [ctypes.c_void_p]
    return kernel, advapi, shell


_kernel, _advapi, _shell = _calls()


class Reader:
    """The processor's temperature, as Hanami Sensors last read it - asking it for a new reading
    each time, and starting it (on a thread of its own) when its readings have gone stale."""

    def __init__(self, memory: str = MEMORY, wanted: str = WANTED, service: str | None = SERVICE):
        self.memory, self.wanted, self.service = memory, wanted, service
        self._mapping = self._view = self._event = None
        self._started_at = -START_AGAIN
        self._last_new = time.monotonic()
        self._last_sequence = None
        self._last_good: tuple | None = None

    def temperature(self) -> float | None:
        self._ask()
        reading = self._read() or self._last_good          # caught mid-write: the one before
        self._last_good = reading
        now = time.monotonic()
        if reading is not None and reading[0] != self._last_sequence:
            self._last_sequence, self._last_new = reading[0], now
        if self.service and now - self._last_new > STALE and now - self._started_at > START_AGAIN:
            self._started_at = now
            threading.Thread(target=start, args=(self.service,), name='hanami-sensors', daemon=True).start()
        if reading is None:
            return None
        _, status, read_at, celsius = reading
        fresh = abs(time.time() - read_at / 1000) < FRESH
        return celsius if status == 0 and fresh and celsius == celsius else None

    def _ask(self) -> None:
        if not self._event:
            self._event = _kernel.OpenEventW(_EVENT_MODIFY_STATE, False, self.wanted)
        if self._event:
            _kernel.SetEvent(self._event)

    def _read(self) -> tuple | None:
        """(sequence, status, when it was read in ms since 1970, °C) - None if there is nothing to
        read, or it was being written both times it was looked at."""
        if not self._view:
            self._mapping = _kernel.OpenFileMappingW(_FILE_MAP_READ, False, self.memory)
            if not self._mapping:
                return None
            self._view = _kernel.MapViewOfFile(self._mapping, _FILE_MAP_READ, 0, 0, SIZE)
            if not self._view:
                _kernel.CloseHandle(self._mapping)
                self._mapping = None
                return None
        for attempt in range(20):
            if attempt:
                time.sleep(0)                               # the service is writing: a moment
            raw = ctypes.string_at(self._view, 32)
            magic, layout, sequence, status, read_at, celsius = struct.unpack('<IIIiqd', raw)
            if magic != MAGIC or layout != LAYOUT:
                return None
            if sequence % 2 == 0 and struct.unpack_from('<I', ctypes.string_at(self._view + 8, 4))[0] == sequence:
                return sequence, status, read_at, celsius
        return None


def service_state(name: str = SERVICE) -> str:
    """'missing', or how it is: 'stopped', 'running', 'starting' and so on."""
    manager = _advapi.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
    if not manager:
        return 'missing'
    try:
        service = _advapi.OpenServiceW(manager, name, _SERVICE_QUERY_STATUS)
        if not service:
            return 'missing'
        try:
            status = (wintypes.DWORD * 7)()
            if not _advapi.QueryServiceStatus(service, status):
                return 'unknown'
            return _STATES.get(status[1], 'unknown')
        finally:
            _advapi.CloseServiceHandle(service)
    finally:
        _advapi.CloseServiceHandle(manager)


def start(name: str = SERVICE) -> bool:
    """Start the service (signed-in users may); whether it is running or on its way."""
    manager = _advapi.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
    if not manager:
        return False
    try:
        service = _advapi.OpenServiceW(manager, name, _SERVICE_START)
        if not service:
            return False
        try:
            return bool(_advapi.StartServiceW(service, 0, None)) or \
                ctypes.get_last_error() == _ERROR_SERVICE_ALREADY_RUNNING
        finally:
            _advapi.CloseServiceHandle(service)
    finally:
        _advapi.CloseServiceHandle(manager)


# --------------------------------------------------------------------------- installing it

@dataclass(frozen=True)
class State:
    installed: str          # the installed service's version ('' if it isn't)
    bundled: str            # the version this Hanami carries ('' if none: a build without it)
    pawnio: bool            # PawnIO is installed (FanControl and LibreHardwareMonitor install it)
    dotnet: bool            # Microsoft's .NET 10 runtime is installed

    @property
    def outdated(self) -> bool:
        return bool(self.installed and self.bundled and _key(self.bundled) > _key(self.installed))


def _key(version: str) -> tuple:
    return tuple(int(part) if part.isdigit() else 0 for part in version.split('.'))


def bundled_folder() -> Path:
    """Where this Hanami carries the service and its setup: beside Hanami.exe - or, run from its
    source, in its last build."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / 'sensors'
    return Path(__file__).resolve().parents[2] / 'dist' / 'Hanami' / 'sensors'


def state() -> State:
    from .installer import exe_version
    installed = exe_version(INSTALLED) if INSTALLED.is_file() and service_state() != 'missing' else ''
    service = bundled_folder() / 'service' / 'HanamiSensors.exe'
    bundled = exe_version(service) if service.is_file() and (bundled_folder() / 'HanamiSensorsSetup.exe').is_file() else ''
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                       r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO'))
        pawnio = True
    except OSError:
        pawnio = False
    runtimes = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'dotnet' / 'shared' / 'Microsoft.NETCore.App'
    dotnet = any(runtime.name.split('.')[0] == '10' for runtime in runtimes.glob('*')) if runtimes.is_dir() else False
    return State(installed, bundled, pawnio, dotnet)


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('fMask', ctypes.c_ulong), ('hwnd', wintypes.HWND),
                ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
                ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                ('dwHotKey', wintypes.DWORD), ('hIconOrMonitor', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]


def run_setup(action: str) -> str:
    """Install ('--install') or remove ('--uninstall') the service, through its setup run with
    administrator permission - Windows asks first. Waits for it; what went wrong, if anything."""
    setup = bundled_folder() / 'HanamiSensorsSetup.exe'
    if not setup.is_file():
        return 'Hanami Sensors isn’t in this build of Hanami.'
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040 | 0x00000100            # SEE_MASK_NOCLOSEPROCESS, SEE_MASK_NOASYNC
    info.lpVerb, info.lpFile, info.lpParameters = 'runas', str(setup), action
    info.lpDirectory, info.nShow = str(setup.parent), 0
    if not _shell.ShellExecuteExW(ctypes.byref(info)):
        return '' if ctypes.get_last_error() == _ERROR_CANCELLED else 'Its setup wouldn’t start.'
    if not info.hProcess:
        return 'Its setup wouldn’t start.'
    try:
        _kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = wintypes.DWORD()
        _kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    finally:
        _kernel.CloseHandle(info.hProcess)
    return SETUP_ANSWERS.get(code.value, f'Its setup failed ({code.value}).')
