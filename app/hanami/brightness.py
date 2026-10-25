"""Monitors' brightness over DDC/CI (dxva2's monitor configuration), read and set as the monitor's
own buttons would. Only monitors that speak it have any: a laptop's built-in screen doesn't, and
some monitors have it off in their own menus.

DDC/CI is slow - tens of ms a call, while the monitor answers down its cable - so it all runs on a
thread of its own (Monitors), which alone holds the monitors' handles. Looks go to it, and
settings: the newest value for a monitor takes the place of one not yet sent, so a slider dragged
sends no more than the monitor can take.
"""

from __future__ import annotations

import ctypes
import threading
import time
from dataclasses import dataclass
from ctypes import wintypes
from typing import Callable

BRIGHTNESS = 0x10           # the VCP code for luminance
TRIES = 3                   # a monitor sometimes misses a call: tried again, after RETRY s
RETRY = 0.05
SETTLE = 1.5                # s after a monitor is set during which it isn't asked: it doesn't answer


@dataclass(frozen=True)
class Monitor:
    key: str                # its display (\\.\DISPLAY1) and its place among that display's monitors
    name: str               # as Windows names it (from the monitor's EDID), or "Screen 2" with none
    value: int              # its brightness, % of its own most


# ---------------------------------------------------------------------- Windows

_user = ctypes.WinDLL('user32', use_last_error=True)
try:
    _dxva2 = ctypes.WinDLL('dxva2', use_last_error=True)
except OSError:             # (Windows N without its media parts, say)
    _dxva2 = None


class _MonitorInfo(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT), ('work', wintypes.RECT),
                ('flags', wintypes.DWORD), ('device', wintypes.WCHAR * 32)]


class _Physical(ctypes.Structure):
    _pack_ = 1
    _fields_ = [('handle', wintypes.HANDLE), ('description', wintypes.WCHAR * 128)]


class _Luid(ctypes.Structure):
    _fields_ = [('low', wintypes.DWORD), ('high', wintypes.LONG)]


class _PathSource(ctypes.Structure):
    _fields_ = [('adapter', _Luid), ('id', ctypes.c_uint32), ('mode', ctypes.c_uint32), ('flags', ctypes.c_uint32)]


class _PathTarget(ctypes.Structure):
    _fields_ = [('adapter', _Luid), ('id', ctypes.c_uint32), ('mode', ctypes.c_uint32),
                ('technology', ctypes.c_uint32), ('rotation', ctypes.c_uint32), ('scaling', ctypes.c_uint32),
                ('refresh', ctypes.c_uint32 * 2), ('ordering', ctypes.c_uint32), ('available', wintypes.BOOL),
                ('flags', ctypes.c_uint32)]


class _Path(ctypes.Structure):
    _fields_ = [('source', _PathSource), ('target', _PathTarget), ('flags', ctypes.c_uint32)]


class _Header(ctypes.Structure):
    _fields_ = [('type', ctypes.c_uint32), ('size', ctypes.c_uint32), ('adapter', _Luid), ('id', ctypes.c_uint32)]


class _SourceName(ctypes.Structure):
    _fields_ = [('header', _Header), ('gdi', wintypes.WCHAR * 32)]


class _TargetName(ctypes.Structure):
    _fields_ = [('header', _Header), ('flags', ctypes.c_uint32), ('technology', ctypes.c_uint32),
                ('maker', ctypes.c_uint16), ('product', ctypes.c_uint16), ('connector', ctypes.c_uint32),
                ('friendly', wintypes.WCHAR * 64), ('path', wintypes.WCHAR * 128)]


_MODE_SIZE = 64             # a DISPLAYCONFIG_MODE_INFO: only room is made for them
_ONLY_ACTIVE = 2
_SOURCE_NAME, _TARGET_NAME = 1, 2
_EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                               wintypes.LPARAM)
_user.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, _EnumProc, wintypes.LPARAM]
_user.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
_user.GetDisplayConfigBufferSizes.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                              ctypes.POINTER(ctypes.c_uint32)]
_user.GetDisplayConfigBufferSizes.restype = wintypes.LONG
_user.QueryDisplayConfig.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
                                     ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p, ctypes.c_void_p]
_user.QueryDisplayConfig.restype = wintypes.LONG
_user.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
_user.DisplayConfigGetDeviceInfo.restype = wintypes.LONG
if _dxva2 is not None:
    _dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [wintypes.HMONITOR, ctypes.POINTER(wintypes.DWORD)]
    _dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [wintypes.HMONITOR, wintypes.DWORD, ctypes.POINTER(_Physical)]
    _dxva2.DestroyPhysicalMonitors.argtypes = [wintypes.DWORD, ctypes.POINTER(_Physical)]
    _dxva2.GetVCPFeatureAndVCPFeatureReply.argtypes = [wintypes.HANDLE, wintypes.BYTE, ctypes.c_void_p,
                                                       ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    _dxva2.SetVCPFeature.argtypes = [wintypes.HANDLE, wintypes.BYTE, wintypes.DWORD]


def _displays() -> list[tuple[int, str, int, int]]:
    """The displays as Windows has them: (HMONITOR, its GDI name, its left and top)."""
    found = []

    def each(hmonitor, _dc, _rect, _data):
        info = _MonitorInfo()
        info.size = ctypes.sizeof(info)
        if _user.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            found.append((hmonitor, info.device, info.monitor.left, info.monitor.top))
        return True
    _user.EnumDisplayMonitors(None, None, _EnumProc(each), 0)
    return found


def friendly_names() -> dict[str, list[str]]:
    """Each display's monitors' names, as Windows has them from their EDID ("DELL G2524H"), by the
    display's GDI name - more than one only while it is duplicated."""
    paths, modes = ctypes.c_uint32(), ctypes.c_uint32()
    if _user.GetDisplayConfigBufferSizes(_ONLY_ACTIVE, ctypes.byref(paths), ctypes.byref(modes)):
        return {}
    path_info = (_Path * max(1, paths.value))()
    mode_info = (ctypes.c_byte * (_MODE_SIZE * max(1, modes.value)))()
    if _user.QueryDisplayConfig(_ONLY_ACTIVE, ctypes.byref(paths), path_info, ctypes.byref(modes), mode_info, None):
        return {}
    names: dict[str, list[str]] = {}
    for path in path_info[:paths.value]:
        source = _SourceName()
        source.header.type, source.header.size = _SOURCE_NAME, ctypes.sizeof(source)
        source.header.adapter, source.header.id = path.source.adapter, path.source.id
        target = _TargetName()
        target.header.type, target.header.size = _TARGET_NAME, ctypes.sizeof(target)
        target.header.adapter, target.header.id = path.target.adapter, path.target.id
        if _user.DisplayConfigGetDeviceInfo(ctypes.byref(source)):
            continue
        friendly = target.friendly if not _user.DisplayConfigGetDeviceInfo(ctypes.byref(target)) else ''
        names.setdefault(source.gdi, []).append(friendly)
    return names


def _handle(monitor: _Physical) -> int:
    """A monitor's handle, as a number. They are numbered across the whole session from 0 - the
    first program to open monitors gets 0 - and ctypes reads a handle of 0 as None. Hanami 0.1.27
    took that None for no monitor, and never set the Dell, its first."""
    return monitor.handle or 0


class _Ddc:
    """The monitors' handles - held from one look until the next."""

    def __init__(self):
        self._held: list[tuple[int, ctypes.Array]] = []

    def open(self) -> list[tuple[str, str, tuple[int, int], int]]:
        """Every monitor Windows has: (key, name, (left, top), handle) - whether or not it answers."""
        self.close()
        if _dxva2 is None:
            return []
        names = friendly_names()
        found = []
        for hmonitor, device, left, top in _displays():
            count = wintypes.DWORD()
            if not _dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmonitor, ctypes.byref(count)) or not count.value:
                continue
            physical = (_Physical * count.value)()
            if not _dxva2.GetPhysicalMonitorsFromHMONITOR(hmonitor, count.value, physical):
                continue
            self._held.append((count.value, physical))
            friendly = names.get(device, [])
            for index, monitor in enumerate(physical):
                name = friendly[index] if index < len(friendly) else ''
                found.append((f'{device}#{index}', name, (left, top), _handle(monitor)))
        return found

    @staticmethod
    def read(handle) -> tuple[int, int] | None:
        """A monitor's brightness and its most - None if it doesn't answer."""
        current, most = wintypes.DWORD(), wintypes.DWORD()
        for attempt in range(TRIES):
            if _dxva2.GetVCPFeatureAndVCPFeatureReply(handle, BRIGHTNESS, None, ctypes.byref(current),
                                                      ctypes.byref(most)) and most.value:
                return current.value, most.value
            time.sleep(RETRY)
        return None

    @staticmethod
    def set(handle, value: int) -> bool:
        """(dxva2 itself waits as long as DDC/CI asks, after each: ~60 ms a set.)"""
        for attempt in range(TRIES):
            if _dxva2.SetVCPFeature(handle, BRIGHTNESS, value):
                return True
            time.sleep(RETRY)
        return False

    def close(self) -> None:
        for count, physical in self._held:
            _dxva2.DestroyPhysicalMonitors(count, physical)
        self._held = []


def _named(found: list) -> list[tuple[str, str, int]]:
    """The monitors in order across the desk, left to right - (key, name, handle), each with a name
    of its own: "Screen 2" for one Windows has none for, "DELL G2524H 2" for a second of the same."""
    found = sorted(found, key=lambda m: (m[2], m[0]))
    named, seen = [], {}
    for place, (key, name, corner, handle) in enumerate(found, 1):
        name = name.strip() or f'Screen {place}'
        seen[name] = seen.get(name, 0) + 1
        named.append((key, name if seen[name] == 1 else f'{name} {seen[name]}', handle))
    return named


class Monitors:
    """The monitors' brightness, on a thread of its own. look() reads every monitor's - found is
    then called, on that thread, with them (a list of Monitor) - and set() changes one's.

    A monitor just set doesn't answer for a while (a second, for this PC's TYPEC): a look in that
    time doesn't ask it, and has it at what it was set to. One that once answered and doesn't now
    keeps the brightness it last had - its slider doesn't come and go."""

    def __init__(self, found: Callable[[list[Monitor]], None], ddc=None):
        self._found = found
        self._ddc = ddc or _Ddc()
        self._work = threading.Condition()
        self._look = False
        self._wanted: dict[str, int] = {}       # key: brightness (%) still to be sent
        self._thread: threading.Thread | None = None
        # the thread's alone:
        self._handles: dict[str, int] = {}      # key: its handle, as of the last look
        self._known: dict[str, tuple[int, int]] = {}    # key: its brightness (%), its own most
        self._set_at: dict[str, float] = {}

    def look(self) -> None:
        with self._work:
            self._look = True
            self._go()

    def set(self, key: str, percent: int) -> None:
        with self._work:
            self._wanted[key] = max(0, min(100, int(percent)))
            self._go()

    def _go(self) -> None:
        self._work.notify()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='hanami-brightness', daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            with self._work:
                while not self._look and not self._wanted:
                    self._work.wait()
                look, self._look = self._look, False
                wanted, self._wanted = self._wanted, {}
            for key, percent in wanted.items():         # what was asked for first: a look may follow
                handle, (_, most) = self._handles.get(key), self._known.get(key, (0, 0))
                if handle is not None and most and self._ddc.set(handle, round(percent * most / 100)):
                    self._known[key] = percent, most
                    self._set_at[key] = time.monotonic()
            if look:
                self._found(self._read())

    def _read(self) -> list[Monitor]:
        try:
            opened = _named(self._ddc.open())
        except OSError:
            opened = []
        self._handles = {key: handle for key, _, handle in opened}
        found = []
        for key, name, handle in opened:
            if time.monotonic() - self._set_at.get(key, -SETTLE) >= SETTLE or key not in self._known:
                reading = self._ddc.read(handle)
                if reading is not None:
                    current, most = reading
                    self._known[key] = round(current * 100 / most), most
            if key in self._known:
                found.append(Monitor(key, name, self._known[key][0]))
        return found
