"""What the PC is doing, for the edge panel's stats page: how busy the processor is and how much
memory is in use, from Windows - and, from NVIDIA's driver (nvml.dll) where there is one, how busy
the graphics card is, its memory and its temperature.

The processor's temperature comes from Hanami Sensors (sensors.py), where it is installed: Windows
gives no program a processor's temperature on PCs like this one - it takes a driver to read.

Sampled only while the stats page is in sight: a sample takes well under a millisecond.
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from . import sensors

_NVML_PLACES = (Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'nvml.dll',
                Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'NVIDIA Corporation' / 'NVSMI' / 'nvml.dll')


@dataclass(frozen=True)
class Stats:
    cpu: float | None                       # % busy, all cores, since the last sample (None: the first)
    ram: tuple[int, int]                    # bytes in use, bytes in all
    gpu: float | None = None                # % busy (None: no NVIDIA card)
    vram: tuple[int, int] | None = None     # bytes in use, bytes in all
    gpu_temp: int | None = None             # °C
    cpu_temp: float | None = None           # °C, from Hanami Sensors (None: it isn't installed)


class _MemoryStatus(ctypes.Structure):
    _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD), ('total', ctypes.c_ulonglong),
                ('free', ctypes.c_ulonglong), ('page_total', ctypes.c_ulonglong), ('page_free', ctypes.c_ulonglong),
                ('virtual_total', ctypes.c_ulonglong), ('virtual_free', ctypes.c_ulonglong),
                ('extended', ctypes.c_ulonglong)]


class _Utilization(ctypes.Structure):
    _fields_ = [('gpu', ctypes.c_uint), ('memory', ctypes.c_uint)]


class _GpuMemory(ctypes.Structure):
    _fields_ = [('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]


def _filetime(value: wintypes.FILETIME) -> int:
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


class Sampler:
    """Takes samples one after another: how busy the processor is comes from the time between
    two of them."""

    def __init__(self):
        self._kernel = ctypes.WinDLL('kernel32')
        self._kernel.GetSystemTimes.argtypes = [ctypes.POINTER(wintypes.FILETIME)] * 3
        self._kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MemoryStatus)]
        self._times: tuple[int, int] | None = None          # (busy + idle, idle), at the last sample
        self._nvml = None
        self._gpu = None
        self._looked_for_gpu = False
        self.sensors = sensors.Reader()

    def prepare(self) -> None:
        """Find the graphics card, on a thread of its own: loading NVIDIA's driver takes a good
        part of a second's tenth, which would stall the panel as it slides. Until then, samples
        have no card in them."""
        if not self._looked_for_gpu:
            self._looked_for_gpu = True
            threading.Thread(target=self._find_gpu, name='hanami-gpu', daemon=True).start()

    def take(self) -> Stats:
        return Stats(self._cpu(), self._ram(), *self._card(), self.sensors.temperature())

    def _cpu(self) -> float | None:
        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not self._kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        now = (_filetime(kernel) + _filetime(user), _filetime(idle))       # kernel time counts idle time too
        last, self._times = self._times, now
        if last is None or now[0] <= last[0]:
            return None
        spent, idled = now[0] - last[0], now[1] - last[1]
        return max(0.0, min(100.0, 100.0 * (spent - idled) / spent))

    def _ram(self) -> tuple[int, int]:
        status = _MemoryStatus()
        status.length = ctypes.sizeof(_MemoryStatus)
        if not self._kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0, 0
        return status.total - status.free, status.total

    def _card(self) -> tuple:
        """The graphics card's (busy %, (memory used, in all), °C) - Nones without NVIDIA's driver."""
        self.prepare()
        if self._gpu is None:
            return None, None, None
        nvml, gpu = self._nvml, self._gpu
        busy, memory, temp = _Utilization(), _GpuMemory(), ctypes.c_uint()
        load = float(busy.gpu) if nvml.nvmlDeviceGetUtilizationRates(gpu, ctypes.byref(busy)) == 0 else None
        vram = (memory.used, memory.total) if nvml.nvmlDeviceGetMemoryInfo(gpu, ctypes.byref(memory)) == 0 else None
        heat = int(temp.value) if nvml.nvmlDeviceGetTemperature(gpu, 0, ctypes.byref(temp)) == 0 else None
        return load, vram, heat

    def _find_gpu(self) -> None:
        for place in _NVML_PLACES:
            if not place.is_file():
                continue
            try:
                nvml = ctypes.WinDLL(str(place))
                for name in ('nvmlDeviceGetHandleByIndex_v2', 'nvmlDeviceGetUtilizationRates',
                             'nvmlDeviceGetMemoryInfo', 'nvmlDeviceGetTemperature'):
                    getattr(nvml, name).restype = ctypes.c_int
                if nvml.nvmlInit_v2() != 0:
                    continue
                gpu = ctypes.c_void_p()
                if nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(gpu)) != 0:
                    continue
            except (OSError, AttributeError):
                continue
            self._nvml = nvml
            self._gpu = gpu                     # last: take() goes by this, from the windows' thread
            return
