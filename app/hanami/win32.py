"""The few Win32 calls Hanami needs, made through ctypes."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
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
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD

PROCESS_QUERY_LIMITED_INFORMATION, SYNCHRONIZE, WAIT_TIMEOUT = 0x1000, 0x00100000, 0x102
CREATE_NO_WINDOW = 0x08000000

user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.PrivateExtractIconsW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
                                        wintypes.UINT, wintypes.UINT]
user32.PrivateExtractIconsW.restype = wintypes.UINT
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
WM_HOTKEY = 0x0312
shell32 = ctypes.WinDLL('shell32', use_last_error=True)
shell32.SHChangeNotify.argtypes = [wintypes.LONG, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
SHCNE_UPDATEITEM, SHCNF_PATHW, SHCNF_FLUSH = 0x00002000, 0x0005, 0x1000


# --------------------------------------------------------------------------- icons

def exe_icon(path: Path, size: int):
    """The icon inside an exe, read from the file itself as a QImage - or None.

    Not through the shell, as QFileIconProvider goes: Windows caches icons by
    path, so an exe rebuilt or updated in place keeps showing its old icon
    there, sometimes until the next sign-in.
    """
    from PySide6.QtGui import QImage
    icon = wintypes.HICON()
    if user32.PrivateExtractIconsW(str(path), 0, size, size, ctypes.byref(icon), None, 1, 0) != 1 or not icon:
        return None
    try:
        image = QImage.fromHICON(icon.value)
    finally:
        user32.DestroyIcon(icon)
    return None if image.isNull() else image


def icon_changed(*paths: Path) -> None:
    """Tell Windows these files changed, so the Start menu, taskbar and Explorer drop their cached icons."""
    for path in paths:
        shell32.SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW | SHCNF_FLUSH, ctypes.c_wchar_p(str(path)), None)


class _Programs:
    """Which programs run as this user, by their full paths - each process looked at once. Its
    handle is kept while it runs, and that keeps Windows from giving its number to another process
    meanwhile: a number seen before is the same program still. Reading every process's path anew
    took 8-25 ms, every 2 s."""

    def __init__(self):
        self._known: dict[int, tuple[int, str]] = {}       # pid: (handle, path)
        self._lock = threading.Lock()

    def running(self) -> set[str]:
        pids = (wintypes.DWORD * 4096)()
        size = wintypes.DWORD()
        if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(size)):
            return set()
        now = pids[:size.value // ctypes.sizeof(wintypes.DWORD)]
        with self._lock:
            present = set(now)
            for pid, (handle, _) in list(self._known.items()):
                if pid not in present or kernel32.WaitForSingleObject(handle, 0) != WAIT_TIMEOUT:
                    kernel32.CloseHandle(handle)            # it has gone: its number may be given again
                    del self._known[pid]
            buffer = ctypes.create_unicode_buffer(32768)
            for pid in now:
                if pid in self._known:
                    continue
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
                if not handle:
                    continue
                length = wintypes.DWORD(len(buffer))
                if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                    self._known[pid] = (handle, os.path.normcase(buffer.value))
                else:
                    kernel32.CloseHandle(handle)
            return {path for _, path in self._known.values()}


_programs = _Programs()


def running_programs() -> set[str]:
    """The full paths, lower case, of every program running as this user."""
    return _programs.running()


# --------------------------------------------------------------------------- the window in front

class _MonitorInfo(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT), ('rcWork', wintypes.RECT),
                ('dwFlags', wintypes.DWORD)]


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.MonitorFromWindow.argtypes, user32.MonitorFromWindow.restype = [wintypes.HWND, wintypes.DWORD], wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetAsyncKeyState.argtypes, user32.GetAsyncKeyState.restype = [ctypes.c_int], ctypes.c_short
_DESKTOP_CLASSES = {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'}


def fullscreen_in_front() -> bool:
    """Whether the window in front fills its screen - a game, a video, a presentation (the desktop
    itself, which fills it too, doesn't count)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, name, len(name))
    if name.value in _DESKTOP_CLASSES:
        return False
    rect, info = wintypes.RECT(), _MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)) \
            or not user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
        return False
    screen = info.rcMonitor
    return rect.left <= screen.left and rect.top <= screen.top and rect.right >= screen.right \
        and rect.bottom >= screen.bottom


def buttons_down() -> bool:
    """Whether a mouse button is held - dragging something, say."""
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x01, 0x02, 0x04))    # left, right, middle


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
