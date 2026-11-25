"""Being told by Windows when the sound changes elsewhere (audio.Watcher).

Nothing here changes the real sound: Windows' callbacks are called by the test itself, through
the COM objects Hanami gives Windows, as Windows would call them.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
import unittest
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from hanami import audio  # noqa: E402


def _query(obj: audio._ComObject, iid: audio.GUID):
    out = ctypes.c_void_p()
    result = audio._call(obj.pointer, 0, ctypes.byref(iid), ctypes.byref(out),
                         argtypes=(ctypes.c_void_p, ctypes.c_void_p), restype=ctypes.c_long)
    return result, out.value


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.told = threading.Event()
        self.watcher = audio.Watcher(self.told.set)
        time.sleep(0.3)
        self.told.clear()

    def test_it_is_listening_to_windows(self):
        self.assertTrue(self.watcher.thread.is_alive(), 'registered with Windows, and waiting')

    def test_its_objects_answer_as_com_objects(self):
        for obj, iid in ((self.watcher.client, audio.IID_IMMNotificationClient),
                         (self.watcher.volume_callback, audio.IID_IAudioEndpointVolumeCallback)):
            self.assertEqual(_query(obj, iid), (0, obj.pointer.value))
            self.assertEqual(_query(obj, audio.IID_IUnknown), (0, obj.pointer.value))
            self.assertEqual(_query(obj, audio.IID_IPolicyConfig)[0], audio._E_NOINTERFACE, 'and not as others')
            self.assertEqual(audio._call(obj.pointer, 1, restype=wintypes.ULONG), 1)     # AddRef

    def test_a_volume_or_mute_changed(self):
        audio._call(self.watcher.volume_callback.pointer, 3, None, argtypes=(ctypes.c_void_p,),
                    restype=ctypes.c_long)                                             # OnNotify
        self.assertTrue(self.told.is_set())

    def test_the_sound_moved_to_another_output(self):
        audio._call(self.watcher.client.pointer, 6, 0, 0, 'an output', argtypes=(ctypes.c_int, ctypes.c_int,
                    wintypes.LPCWSTR), restype=ctypes.c_long)                          # OnDefaultDeviceChanged
        self.assertTrue(self.told.is_set())

    def test_an_output_plugged_in_or_out(self):
        for index in (4, 5):                                                           # OnDeviceAdded, -Removed
            self.told.clear()
            audio._call(self.watcher.client.pointer, index, 'an output', argtypes=(wintypes.LPCWSTR,),
                        restype=ctypes.c_long)
            self.assertTrue(self.told.is_set())

    def test_a_property_changing_is_not_news(self):
        key = audio.PROPERTYKEY(audio.GUID(), 0)
        audio._call(self.watcher.client.pointer, 7, 'an output', ctypes.byref(key),
                    argtypes=(wintypes.LPCWSTR, ctypes.c_void_p), restype=ctypes.c_long)   # OnPropertyValueChanged
        self.assertFalse(self.told.is_set())

    def test_a_listener_that_raises_is_kept_from_windows(self):
        watcher = audio.Watcher(lambda: 1 / 0)
        result = audio._call(watcher.volume_callback.pointer, 3, None, argtypes=(ctypes.c_void_p,),
                             restype=ctypes.c_long)
        self.assertEqual(result, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
