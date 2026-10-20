"""The few Win32 calls Hanami needs, made through ctypes."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import winreg
from ctypes import wintypes
from pathlib import Path

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)
psapi.EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
psapi.EnumProcesses.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
CREATE_NO_WINDOW = 0x08000000


def running_programs() -> set[str]:
    """The full paths, lower case, of every program running as this user."""
    pids = (wintypes.DWORD * 4096)()
    size = wintypes.DWORD()
    if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(size)):
        return set()
    found = set()
    buffer = ctypes.create_unicode_buffer(32768)
    for pid in pids[:size.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            continue
        length = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            found.add(os.path.normcase(buffer.value))
        kernel32.CloseHandle(handle)
    return found


# --------------------------------------------------------------------------- start with Windows

_RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
_RUN_NAME = 'Hanami'


def launch_command() -> str:
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" --startup'
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    main = Path(__file__).resolve().parents[1] / 'main.py'
    return f'"{pythonw}" "{main}" --startup'


def starts_with_windows() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _RUN_NAME)
            return True
    except OSError:
        return False


def set_start_with_windows(enabled: bool) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, _RUN_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, _RUN_NAME)
            except FileNotFoundError:
                pass


# --------------------------------------------------------------------------- Start menu

def start_menu() -> Path:
    chosen = os.environ.get('HANAMI_START_MENU')        # tests keep their shortcuts to themselves
    if chosen:
        return Path(chosen)
    return Path(os.environ.get('APPDATA', str(Path.home()))) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs'


def make_shortcut(link: Path, target: Path) -> bool:
    """A Start menu shortcut, through Windows' own scripting object."""
    def quoted(path) -> str:
        return "'" + str(path).replace("'", "''") + "'"
    script = (f'$s = (New-Object -ComObject WScript.Shell).CreateShortcut({quoted(link)}); '
              f'$s.TargetPath = {quoted(target)}; $s.WorkingDirectory = {quoted(target.parent)}; $s.Save()')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=30)
    return result.returncode == 0 and link.exists()


def app_data() -> Path:
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Hanami'
