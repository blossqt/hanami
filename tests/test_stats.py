"""The edge panel's stats: the processor's temperature from Hanami Sensors' shared memory.

None of this needs Hanami Sensors installed, nor administrator rights: the shared memory is made
here (or by the built service run as the user, --console), under Local\\ names of the tests' own.
The built service and setup are used when they are there - build_app.ps1, or sensors\\build.ps1.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from hanami import sensors, stats  # noqa: E402

BUILT = Path(os.environ.get('LOCALAPPDATA', '')) / 'HanamiBuild' / 'sensors' / 'out'

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.CreateFileMappingW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.LPCWSTR]
kernel.CreateFileMappingW.restype = wintypes.HANDLE
kernel.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
kernel.MapViewOfFile.restype = ctypes.c_void_p
kernel.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
kernel.CloseHandle.argtypes = [wintypes.HANDLE]


class _Block:
    """Shared memory laid out as the service lays it, written here."""

    def __init__(self, name: str):
        self.mapping = kernel.CreateFileMappingW(wintypes.HANDLE(-1), None, 0x04, 0, 4096, name)
        self.view = kernel.MapViewOfFile(self.mapping, 0x02, 0, 0, 4096)

    def write(self, sequence: int, status: int, read_at_ms: int, celsius: float) -> None:
        ctypes.memmove(self.view, struct.pack('<IIIiqd', sensors.MAGIC, sensors.LAYOUT, sequence, status,
                                              read_at_ms, celsius), 32)

    def close(self) -> None:
        kernel.UnmapViewOfFile(self.view)
        kernel.CloseHandle(self.mapping)


class ReaderTests(unittest.TestCase):
    def test_a_fresh_reading_and_nothing_else(self):
        name = f'Local\\HanamiSensorsTest{os.getpid()}'
        reader = sensors.Reader(name, name + 'Wanted', service=None)
        self.assertIsNone(reader.temperature(), 'no service: nothing')
        block = _Block(name)
        try:
            now = int(time.time() * 1000)
            block.write(2, 0, now, 64.25)
            self.assertEqual(reader.temperature(), 64.25)
            block.write(3, 0, now, 70.0)
            self.assertEqual(reader.temperature(), 64.25, 'caught mid-write: the reading before')
            block.write(4, 1, now, float('nan'))
            self.assertIsNone(reader.temperature(), 'no sensor')
            block.write(6, 0, now - 60_000, 64.0)
            self.assertIsNone(reader.temperature(), 'a minute old: not to be shown')
        finally:
            block.close()

    def test_a_stale_reading_starts_the_service_at_once(self):
        # The memory outlives the service while Hanami holds it: a reading there may be long dead,
        # and it is its age - not whether it is new to this reader - that tells.
        from unittest import mock
        name = f'Local\\HanamiSensorsStale{os.getpid()}'
        block = _Block(name)
        started = []
        try:
            with mock.patch.object(sensors, 'start', lambda service: started.append(service)):
                block.write(2, 0, int(time.time() * 1000) - 75 * 60_000, 72.9)       # 75 minutes old
                reader = sensors.Reader(name, name + 'Wanted', service='Stand-in')
                self.assertIsNone(reader.temperature())
                time.sleep(0.2)
                self.assertEqual(started, ['Stand-in'], 'started at the first look, not seconds later')
                block.write(4, 0, int(time.time() * 1000), 73.0)
                reader._started_at = -sensors.START_AGAIN
                self.assertEqual(reader.temperature(), 73.0)
                time.sleep(0.2)
                self.assertEqual(started, ['Stand-in'], 'a fresh reading: running, left alone')
        finally:
            block.close()

    def test_the_sampler_has_it(self):
        sampler = stats.Sampler()
        sampler.sensors = sensors.Reader(f'Local\\HanamiSensorsNone{os.getpid()}', 'Local\\none', service=None)
        self.assertIsNone(sampler.take().cpu_temp, 'without Hanami Sensors: no processor temperature')


@unittest.skipUnless((BUILT / 'HanamiSensorsSetup.exe').is_file(), 'Hanami Sensors not built (sensors\\build.ps1)')
class BuiltTests(unittest.TestCase):
    def test_the_service_as_the_user(self):
        name = f'HanamiSensorsRun{os.getpid()}'
        service = subprocess.Popen([str(BUILT / 'service' / 'HanamiSensors.exe'), '--console', name,
                                    '--fake', '58.5', '--idle', '1.5'])
        try:
            reader = sensors.Reader(f'Local\\{name}', f'Local\\{name}Wanted', service=None)
            until, got = time.monotonic() + 10, None
            while time.monotonic() < until and got is None:
                got = reader.temperature()
                time.sleep(0.1)
            self.assertEqual(got, 58.5, 'read through shared memory')
            readings = []
            for _ in range(6):
                readings.append(reader.temperature())
                time.sleep(0.2)
            self.assertEqual(readings, [58.5] * 6, 'asked over and over: never a torn one')
            self.assertEqual(service.wait(10), 0, 'and it stops by itself, unasked')
        finally:
            if service.poll() is None:
                service.kill()

    def test_the_setup_installs_nothing_changed(self):
        folder = Path(tempfile.mkdtemp(prefix='hs-'))
        try:
            copy = folder / 'sensors'
            shutil.copytree(BUILT, copy)
            setup = str(copy / 'HanamiSensorsSetup.exe')
            self.assertEqual(subprocess.run([setup, '--verify']).returncode, 0, 'as built')
            library = copy / 'service' / 'LibreHardwareMonitorLib.dll'
            data = bytearray(library.read_bytes())
            data[4096] ^= 1
            library.write_bytes(bytes(data))
            self.assertEqual(subprocess.run([setup, '--verify']).returncode, 3, 'one byte changed: refused')
            if not ctypes.windll.shell32.IsUserAnAdmin():
                self.assertEqual(subprocess.run([setup, '--install']).returncode, 2, 'not as administrator: refused')
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
