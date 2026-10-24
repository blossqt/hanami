"""Windows' sound outputs: which there are, which one sound goes to, and moving it to another.

Through Core Audio's COM interfaces, called with ctypes. Choosing the default
output goes through IPolicyConfig - the interface Windows' own Sound settings
use, undocumented but unchanged since Windows 7 - for all three of its roles
(games and media, communications, system sounds), as Settings does.
"""

from __future__ import annotations

import ctypes
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
PKEY_Device_FriendlyName = PROPERTYKEY(GUID.of('A45C254E-DF1C-4EFD-8020-67D146A850E0'), 14)

CLSCTX_ALL = 0x17
E_RENDER = 0                    # outputs, not inputs
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
        raise AudioError(f'Windows would not list its sound outputs ({error})') from None
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
        raise AudioError(f'Windows would not change its sound output ({error})') from None
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
