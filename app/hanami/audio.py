"""Windows' sound outputs: which there are, which one sound goes to, and moving it to another -
and its microphone, muted or not.

Through Core Audio's COM interfaces, called with ctypes. Choosing the default
output goes through IPolicyConfig - the interface Windows' own Sound settings
use, undocumented but unchanged since Windows 7 - for all three of its roles
(games and media, communications, system sounds), as Settings does.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

ole32 = ctypes.WinDLL('ole32')
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = ctypes.c_long
ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_void_p)]
ole32.CoCreateInstance.restype = ctypes.HRESULT
ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
ole32.PropVariantClear.argtypes = [ctypes.c_void_p]


class GUID(ctypes.Structure):
    _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD),
                ('Data4', ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text: str) -> 'GUID':
        import uuid
        raw = uuid.UUID(text).bytes_le
        return cls.from_buffer_copy(raw)


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [('fmtid', GUID), ('pid', wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [('vt', wintypes.WORD), ('reserved', wintypes.WORD * 3), ('pointer', ctypes.c_void_p),
                ('rest', ctypes.c_void_p)]


CLSID_MMDeviceEnumerator = GUID.of('BCDE0395-E52F-467C-8E3D-C4579291692E')
IID_IMMDeviceEnumerator = GUID.of('A95664D2-9614-4F35-A746-DE8DB63617E6')
CLSID_PolicyConfigClient = GUID.of('870AF99C-171D-4F9E-AF0D-E63DF40C2BC9')
IID_IPolicyConfig = GUID.of('F8679F50-850A-41CF-9C72-430F290290C8')
IID_IAudioEndpointVolume = GUID.of('5CDF2C82-841E-4546-9722-0CF74078229A')
PKEY_Device_FriendlyName = PROPERTYKEY(GUID.of('A45C254E-DF1C-4EFD-8020-67D146A850E0'), 14)

CLSCTX_ALL = 0x17
E_RENDER, E_CAPTURE = 0, 1       # outputs; inputs (microphones)
DEVICE_STATE_ACTIVE = 0x1
ROLES = (0, 1, 2)               # eConsole, eMultimedia, eCommunications
VT_LPWSTR = 31


@dataclass(frozen=True)
class Output:
    id: str
    name: str


class AudioError(OSError):
    pass


def _call(obj: ctypes.c_void_p, index: int, *args, argtypes=(), restype=ctypes.HRESULT):
    """Call method index of a COM object's vtable."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])
    return method(obj, *args)


def _release(obj: ctypes.c_void_p) -> None:
    if obj:
        _call(obj, 2, restype=wintypes.ULONG)


def _create(clsid: GUID, iid: GUID) -> ctypes.c_void_p:
    ole32.CoInitializeEx(None, 0x2)          # apartment-threaded; already so on Qt's thread, which is fine
    obj = ctypes.c_void_p()
    ole32.CoCreateInstance(ctypes.byref(clsid), None, CLSCTX_ALL, ctypes.byref(iid), ctypes.byref(obj))
    return obj


def _device_id(device: ctypes.c_void_p) -> str:
    text = ctypes.c_void_p()
    _call(device, 5, ctypes.byref(text), argtypes=(ctypes.c_void_p,))                  # IMMDevice::GetId
    try:
        return ctypes.wstring_at(text.value)
    finally:
        ole32.CoTaskMemFree(text)


def _device_name(device: ctypes.c_void_p) -> str:
    store = ctypes.c_void_p()
    _call(device, 4, 0, ctypes.byref(store), argtypes=(wintypes.DWORD, ctypes.c_void_p))   # OpenPropertyStore
    try:
        value = PROPVARIANT()
        _call(store, 5, ctypes.byref(PKEY_Device_FriendlyName), ctypes.byref(value),
              argtypes=(ctypes.c_void_p, ctypes.c_void_p))                              # IPropertyStore::GetValue
        try:
            return ctypes.wstring_at(value.pointer) if value.vt == VT_LPWSTR and value.pointer else ''
        finally:
            ole32.PropVariantClear(ctypes.byref(value))
    finally:
        _release(store)


def outputs() -> list[Output]:
    """The sound outputs that are plugged in and turned on, as Windows lists them."""
    try:
        enumerator = _create(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
    except OSError as error:
        raise AudioError(f'Windows did not list the sound outputs ({error})') from None
    try:
        collection = ctypes.c_void_p()
        _call(enumerator, 3, E_RENDER, DEVICE_STATE_ACTIVE, ctypes.byref(collection),
              argtypes=(ctypes.c_int, wintypes.DWORD, ctypes.c_void_p))                 # EnumAudioEndpoints
        try:
            count = wintypes.UINT()
            _call(collection, 3, ctypes.byref(count), argtypes=(ctypes.c_void_p,))       # GetCount
            found = []
            for index in range(count.value):
                device = ctypes.c_void_p()
                _call(collection, 4, index, ctypes.byref(device), argtypes=(wintypes.UINT, ctypes.c_void_p))
                try:
                    found.append(Output(_device_id(device), _device_name(device)))
                finally:
                    _release(device)
            return found
        finally:
            _release(collection)
    finally:
        _release(enumerator)


def current() -> str:
    """The id of the output sound goes to now, or '' if there is none."""
    try:
        enumerator = _create(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
    except OSError:
        return ''
    try:
        device = ctypes.c_void_p()
        try:
            _call(enumerator, 4, E_RENDER, 1, ctypes.byref(device),
                  argtypes=(ctypes.c_int, ctypes.c_int, ctypes.c_void_p))               # GetDefaultAudioEndpoint
        except OSError:
            return ''                                       # none plugged in
        try:
            return _device_id(device)
        finally:
            _release(device)
    finally:
        _release(enumerator)


def choose(output_id: str) -> None:
    """Send the sound to this output, for everything, as Windows' Sound settings would."""
    try:
        policy = _create(CLSID_PolicyConfigClient, IID_IPolicyConfig)
    except OSError as error:
        raise AudioError(f'Windows did not change the sound output ({error})') from None
    try:
        for role in ROLES:
            _call(policy, 13, output_id, role, argtypes=(wintypes.LPCWSTR, ctypes.c_int))   # SetDefaultEndpoint
    finally:
        _release(policy)


def next_output(chosen: list[str]) -> Output | None:
    """The output after the one sound goes to now, among those chosen to switch between (all of
    them, with fewer than two chosen and plugged in) - or None with nothing to switch to."""
    present = outputs()
    ring = [o for o in present if o.id in chosen]
    if len(ring) < 2:
        ring = present
    if len(ring) < 2:
        return None
    now = current()
    ids = [o.id for o in ring]
    return ring[(ids.index(now) + 1) % len(ring)] if now in ids else ring[0]


# --------------------------------------------------------------------------- the volume

def _output_volume(enumerator: ctypes.c_void_p) -> ctypes.c_void_p | None:
    """The default output's IAudioEndpointVolume, to be released - None with no output."""
    device = ctypes.c_void_p()
    try:
        _call(enumerator, 4, E_RENDER, 1, ctypes.byref(device),
              argtypes=(ctypes.c_int, ctypes.c_int, ctypes.c_void_p))                   # GetDefaultAudioEndpoint
    except OSError:
        return None
    try:
        return _volume(device)
    finally:
        _release(device)


def volume() -> int | None:
    """How loud the output sound goes to is, 0 to 100 as Windows shows it - None with no output."""
    try:
        enumerator = _create(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
    except OSError:
        return None
    try:
        endpoint = _output_volume(enumerator)
        if endpoint is None:
            return None
        try:
            level = ctypes.c_float()
            _call(endpoint, 9, ctypes.byref(level), argtypes=(ctypes.c_void_p,))    # GetMasterVolumeLevelScalar
            return round(level.value * 100)
        finally:
            _release(endpoint)
    finally:
        _release(enumerator)


def set_volume(percent: int) -> None:
    """Set the output's volume, 0 to 100 - unmuting it, as Windows' own slider does."""
    try:
        enumerator = _create(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
    except OSError as error:
        raise AudioError(f'Windows did not find the sound output ({error})') from None
    try:
        endpoint = _output_volume(enumerator)
        if endpoint is None:
            return
        try:
            _call(endpoint, 7, max(0.0, min(1.0, percent / 100)), None,
                  argtypes=(ctypes.c_float, ctypes.c_void_p))                           # SetMasterVolumeLevelScalar
            muted = wintypes.BOOL()
            _call(endpoint, 15, ctypes.byref(muted), argtypes=(ctypes.c_void_p,))      # GetMute
            if muted.value and percent > 0:
                _call(endpoint, 14, False, None, argtypes=(wintypes.BOOL, ctypes.c_void_p))   # SetMute
        finally:
            _release(endpoint)
    finally:
        _release(enumerator)


# --------------------------------------------------------------------------- the microphone

def _microphones(enumerator: ctypes.c_void_p) -> list[ctypes.c_void_p]:
    """Windows' default microphone, and its default one for calls (as Discord uses) if that is
    another - each an IMMDevice, to be released."""
    found, ids = [], set()
    for role in (0, 2):                                     # eConsole, eCommunications
        device = ctypes.c_void_p()
        try:
            _call(enumerator, 4, E_CAPTURE, role, ctypes.byref(device),
                  argtypes=(ctypes.c_int, ctypes.c_int, ctypes.c_void_p))               # GetDefaultAudioEndpoint
        except OSError:
            continue                                        # none plugged in
        device_id = _device_id(device)
        if device_id in ids:
            _release(device)
        else:
            ids.add(device_id)
            found.append(device)
    return found


def _volume(device: ctypes.c_void_p) -> ctypes.c_void_p:
    volume = ctypes.c_void_p()
    _call(device, 3, ctypes.byref(IID_IAudioEndpointVolume), CLSCTX_ALL, None, ctypes.byref(volume),
          argtypes=(ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p))    # IMMDevice::Activate
    return volume


def mic_muted() -> bool | None:
    """Whether Windows' default microphone is muted - None with no microphone plugged in."""
    try:
        enumerator = _create(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
    except OSError:
        return None
    try:
        devices = _microphones(enumerator)
        if not devices:
            return None
        try:
            volume = _volume(devices[0])
            try:
                muted = wintypes.BOOL()
                _call(volume, 15, ctypes.byref(muted), argtypes=(ctypes.c_void_p,))    # IAudioEndpointVolume::GetMute
                return bool(muted.value)
            finally:
                _release(volume)
        finally:
            for device in devices:
                _release(device)
    finally:
        _release(enumerator)


def mute_mic(muted: bool) -> None:
    """Mute the microphone, or not: Windows' default one, and its default one for calls if that is
    another - so nothing hears it, whichever it records from."""
    try:
        enumerator = _create(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
    except OSError as error:
        raise AudioError(f'Windows did not find the microphone ({error})') from None
    try:
        devices = _microphones(enumerator)
        try:
            for device in devices:
                volume = _volume(device)
                try:
                    _call(volume, 14, bool(muted), None, argtypes=(wintypes.BOOL, ctypes.c_void_p))   # SetMute
                finally:
                    _release(volume)
        finally:
            for device in devices:
                _release(device)
    finally:
        _release(enumerator)


# --------------------------------------------------------------------------- told of changes

# Windows tells whoever asks when the sound moves to another output, an output or microphone comes
# or goes (IMMNotificationClient), or an output's volume or a microphone's mute changes - from the
# keyboard's volume keys, Windows' own flyout, another app (IAudioEndpointVolumeCallback). Hanami
# then looks again at once, rather than at its next look, up to 2 s later. The two are COM objects
# of Hanami's own, made here with ctypes: a vtable of callbacks, each told on a thread of Windows'.

IID_IUnknown = GUID.of('00000000-0000-0000-C000-000000000046')
IID_IMMNotificationClient = GUID.of('7991EEC9-7E89-4D85-8390-6C703CEC60C0')
IID_IAudioEndpointVolumeCallback = GUID.of('657804FA-D6AD-4496-8A60-352752AF4F89')
_S_OK, _E_NOINTERFACE = 0, -2147467262          # 0x80004002, as a signed HRESULT

_QueryInterface = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID),
                                     ctypes.POINTER(ctypes.c_void_p))
_Count = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
_OnText = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)
_OnState = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.DWORD)
_OnDefault = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR)
# OnPropertyValueChanged's PROPERTYKEY (20 bytes) goes by value - on x64, as a pointer to a copy
_OnProperty = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_void_p)
_OnNotify = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)


class _ComObject:
    """A COM object of Hanami's own: its interface pointer (pointer), its methods the callbacks
    given after IUnknown's. It lives as long as Hanami, so it counts no references."""

    def __init__(self, iid: GUID, *methods):
        def query(this, riid, out):
            asked = bytes(riid.contents)
            if asked in (bytes(IID_IUnknown), bytes(iid)):
                out[0] = this
                return _S_OK
            out[0] = None
            return _E_NOINTERFACE
        self._functions = (_QueryInterface(query), _Count(lambda this: 1), _Count(lambda this: 1), *methods)
        self._vtable = (ctypes.c_void_p * len(self._functions))(
            *[ctypes.cast(f, ctypes.c_void_p) for f in self._functions])
        self._object = ctypes.c_void_p(ctypes.addressof(self._vtable))
        self.pointer = ctypes.c_void_p(ctypes.addressof(self._object))


class Watcher:
    """Calls changed() - on a thread of Windows', so it must only hand the news on - whenever the
    sound moves, an output or microphone comes or goes, or a volume or mute changes. It listens to
    the output's volume and the microphones' on a thread of its own, and to new ones each time the
    defaults change."""

    def __init__(self, changed):
        self._changed = changed
        self._again = threading.Event()         # the defaults changed: listen to the new ones
        self._again.set()
        self.client = _ComObject(IID_IMMNotificationClient,
                                 _OnState(lambda this, device, state: self._moved()),
                                 _OnText(lambda this, device: self._moved()),
                                 _OnText(lambda this, device: self._moved()),
                                 _OnDefault(lambda this, flow, role, device: self._moved()),
                                 _OnProperty(lambda this, device, key: _S_OK))
        self.volume_callback = _ComObject(IID_IAudioEndpointVolumeCallback, _OnNotify(lambda this, data: self._tell()))
        self.thread = threading.Thread(target=self._run, name='hanami-sound-watch', daemon=True)
        self.thread.start()

    def _tell(self) -> int:
        try:
            self._changed()
        except Exception:  # noqa: BLE001 - never raised into Windows' thread
            pass
        return _S_OK

    def _moved(self) -> int:
        self._again.set()
        return self._tell()

    def _run(self) -> None:
        ole32.CoInitializeEx(None, 0x0)             # multithreaded: Windows calls back on threads of its own
        try:
            enumerator = _create(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
            _call(enumerator, 6, self.client.pointer, argtypes=(ctypes.c_void_p,))   # RegisterEndpointNotificationCallback
        except OSError:
            return                                  # not told, then: Hanami's looks every 2 s go on
        listened: list[ctypes.c_void_p] = []
        while True:
            self._again.wait()
            time.sleep(0.05)                        # the three roles' changes come together: listened to once
            self._again.clear()
            for endpoint in listened:
                try:
                    _call(endpoint, 4, self.volume_callback.pointer, argtypes=(ctypes.c_void_p,))   # Unregister...
                except OSError:
                    pass
                _release(endpoint)
            listened = []
            try:
                endpoint = _output_volume(enumerator)
                devices = _microphones(enumerator)
            except OSError:
                endpoint, devices = None, []
            try:
                endpoints = ([endpoint] if endpoint is not None else []) + [_volume(d) for d in devices]
            except OSError:
                endpoints = [endpoint] if endpoint is not None else []
            finally:
                for device in devices:
                    _release(device)
            for each in endpoints:
                try:
                    _call(each, 3, self.volume_callback.pointer, argtypes=(ctypes.c_void_p,))   # RegisterControlChangeNotify
                    listened.append(each)
                except OSError:
                    _release(each)


_watcher: Watcher | None = None
_listeners: list = []


def watch(changed) -> None:
    """changed() - on a thread of Windows' - whenever the sound changes elsewhere (Watcher). One
    Watcher, however many listen."""
    global _watcher
    _listeners.append(changed)
    if _watcher is None:
        _watcher = Watcher(lambda: [listener() for listener in list(_listeners)])
