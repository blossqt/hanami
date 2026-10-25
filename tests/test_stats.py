"""The edge panel's stats: the processor's temperature from LibreHardwareMonitor's Remote Web Server
- here a stand-in one, on a port of its own: none of this needs LibreHardwareMonitor installed."""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from hanami import stats  # noqa: E402


def _tree(cpu: list[tuple[str, float]], gpu_temp: float = 80.0, vendor: str = 'amdcpu') -> dict:
    """data.json, as LibreHardwareMonitor 0.9.6 serves it: the computer, its hardware, each kind of
    sensor, the sensors."""
    sensors = [{'id': 10 + i, 'Text': name, 'SensorId': f'/{vendor}/0/temperature/{i}', 'Type': 'Temperature',
                'Value': f'{value:.1f} °C', 'RawValue': value, 'Children': []} for i, (name, value) in enumerate(cpu)]
    return {'id': 0, 'Text': 'Sensor', 'Children': [{'id': 1, 'Text': 'PC', 'Children': [
        {'id': 2, 'Text': 'The processor', 'HardwareId': f'/{vendor}/0', 'Children': [
            {'id': 3, 'Text': 'Temperatures', 'Children': sensors},
            {'id': 4, 'Text': 'Load', 'Children': [{'id': 5, 'Text': 'CPU Total', 'SensorId': f'/{vendor}/0/load/0',
                                                    'Type': 'Load', 'RawValue': 99.0, 'Children': []}]}]},
        {'id': 6, 'Text': 'The graphics card', 'HardwareId': '/gpu-nvidia/0', 'Children': [
            {'id': 7, 'Text': 'Temperatures', 'Children': [{'id': 8, 'Text': 'GPU Core', 'Type': 'Temperature',
                                                            'SensorId': '/gpu-nvidia/0/temperature/0',
                                                            'RawValue': gpu_temp, 'Children': []}]}]}]}]}


class TemperatureTests(unittest.TestCase):
    def test_the_processors_own_sensor(self):
        self.assertEqual(stats.cpu_temperature(_tree([('CCD1 (Tdie)', 68.0), ('Core (Tctl/Tdie)', 71.5)])), 71.5,
                         'AMD: Tctl/Tdie')
        self.assertEqual(stats.cpu_temperature(_tree([('CPU Core #1', 60.0), ('CPU Package', 64.0)], vendor='intelcpu')),
                         64.0, 'Intel: the package')
        self.assertEqual(stats.cpu_temperature(_tree([('A', 55.0), ('B', 58.0)])), 58.0, 'else the hottest')
        self.assertIsNone(stats.cpu_temperature(_tree([])), 'the graphics card’s is not the processor’s')
        self.assertIsNone(stats.cpu_temperature({}))


class _StandIn(BaseHTTPRequestHandler):
    tree: dict = {}

    def do_GET(self):
        body = json.dumps(self.tree).encode()
        self.send_response(200 if self.path == '/data.json' else 404)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class SamplerTests(unittest.TestCase):
    def _until(self, sampler, test, seconds: float = 3.0):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            got = sampler.take()
            if test(got):
                return got
            time.sleep(0.05)
        return sampler.take()

    def test_read_from_libre_hardware_monitor_while_it_runs(self):
        _StandIn.tree = _tree([('Core (Tctl/Tdie)', 72.25)])
        server = ThreadingHTTPServer(('127.0.0.1', 0), _StandIn)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            sampler = stats.Sampler()
            sampler.lhm_url = f'http://127.0.0.1:{server.server_address[1]}/data.json'
            started = time.perf_counter()
            first = sampler.take()
            self.assertLess(time.perf_counter() - started, 0.05, 'asked on a thread: a sample never waits')
            self.assertIsNone(first.cpu_temp, 'not there yet')
            self.assertEqual(self._until(sampler, lambda s: s.cpu_temp is not None).cpu_temp, 72.25)
        finally:
            server.shutdown()
            server.server_close()

    def test_none_without_it(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), _StandIn)
        port = server.server_address[1]
        server.server_close()                                       # nothing on that port now
        sampler = stats.Sampler()
        sampler.lhm_url = f'http://127.0.0.1:{port}/data.json'
        got = self._until(sampler, lambda s: not sampler._lhm_asking and sampler._lhm_next - time.monotonic() > 5, 3)
        self.assertIsNone(got.cpu_temp)
        self.assertGreater(sampler._lhm_next - time.monotonic(), stats.LHM_EVERY, 'asked again only later')


if __name__ == '__main__':
    unittest.main(verbosity=2)
