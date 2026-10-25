"""What the PC is doing, for the edge panel's stats page: how busy the processor is and how much
memory is in use, from Windows - and, from NVIDIA's driver (nvml.dll) where there is one, how busy
the graphics card is, its memory and its temperature.

Windows gives no program the processor's temperature on a PC like this one (no thermal zones): it
takes a driver of its own to read. So that comes from LibreHardwareMonitor, while it runs with its
Remote Web Server on (LHM_URL, on this PC only) - fetched on a thread of its own, the last reading
kept for the next sample. Without it, there is no processor temperature.

Sampled only while the stats page is in sight: a sample takes well under a millisecond.
"""

from __future__ import annotations

import ctypes
import json
import os
import threading
import time
import urllib.request
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

LHM_URL = 'http://127.0.0.1:8085/data.json'       # LibreHardwareMonitor's Remote Web Server, its default port
LHM_EVERY = 1.0         # s between readings from it, while samples are being taken
LHM_AGAIN = 10.0        # s before trying it again, when it didn't answer
LHM_STALE = 5.0         # s a reading is kept for, without a newer one
_NVML_PLACES = (Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'nvml.dll',
                Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'NVIDIA Corporation' / 'NVSMI' / 'nvml.dll')


@dataclass(frozen=True)
class Stats:
    cpu: float | None                       # % busy, all cores, since the last sample (None: the first)
    ram: tuple[int, int]                    # bytes in use, bytes in all
    gpu: float | None = None                # % busy (None: no NVIDIA card)
    vram: tuple[int, int] | None = None     # bytes in use, bytes in all
    gpu_temp: int | None = None             # °C
    cpu_temp: float | None = None           # °C, from LibreHardwareMonitor (None: it isn't running)


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
        self.lhm_url = LHM_URL
        self._cpu_temp: tuple[float, float] | None = None      # (°C, when it was read)
        self._lhm_next = 0.0                                    # when to ask LibreHardwareMonitor next
        self._lhm_asking = False
        self._direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # no proxy for this PC

    def prepare(self) -> None:
        """Find the graphics card, on a thread of its own: loading NVIDIA's driver takes a good
        part of a second's tenth, which would stall the panel as it slides. Until then, samples
        have no card in them."""
        if not self._looked_for_gpu:
            self._looked_for_gpu = True
            threading.Thread(target=self._find_gpu, name='hanami-gpu', daemon=True).start()

    def take(self) -> Stats:
        return Stats(self._cpu(), self._ram(), *self._card(), self._processor_temperature())

    # ------------------------------------------------------------------ LibreHardwareMonitor

    def _processor_temperature(self) -> float | None:
        """The last reading from LibreHardwareMonitor - asking it for a new one, on a thread of
        its own, now and then (more seldom while it doesn't answer)."""
        now = time.monotonic()
        if not self._lhm_asking and now >= self._lhm_next:
            self._lhm_asking = True
            self._lhm_next = now + LHM_EVERY
            threading.Thread(target=self._ask_lhm, name='hanami-lhm', daemon=True).start()
        kept = self._cpu_temp
        return kept[0] if kept is not None and now - kept[1] < LHM_STALE else None

    def _ask_lhm(self) -> None:
        try:
            with self._direct.open(self.lhm_url, timeout=0.8) as answer:
                found = cpu_temperature(json.loads(answer.read().decode('utf-8', 'replace')))
        except (OSError, ValueError):
            found = None
            self._lhm_next = time.monotonic() + LHM_AGAIN
        if found is not None:
            self._cpu_temp = (found, time.monotonic())
        self._lhm_asking = False

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


def cpu_temperature(tree: dict) -> float | None:
    """The processor's temperature in LibreHardwareMonitor's data.json (°C, whatever unit it
    shows): AMD's "Core (Tctl/Tdie)" or Intel's "CPU Package" - else the hottest of the processor's
    temperatures."""
    found: list[tuple[str, float]] = []

    def walk(node: dict) -> None:
        sensor = str(node.get('SensorId', ''))
        if node.get('Type') == 'Temperature' and sensor.startswith(('/amdcpu/', '/intelcpu/')):
            value = node.get('RawValue')
            if isinstance(value, (int, float)) and 0 < value < 150:
                found.append((str(node.get('Text', '')), float(value)))
        for child in node.get('Children') or ():
            if isinstance(child, dict):
                walk(child)

    walk(tree)
    for name, value in found:
        if 'tctl' in name.lower() or 'package' in name.lower():
            return value
    return max((value for _, value in found), default=None)
