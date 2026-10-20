"""Windows user-bound encrypted storage. Tokens never reach the frontend or logs."""
import ctypes
from ctypes import wintypes
import json
import os
from config import DATA_DIRECTORY

PATH = DATA_DIRECTORY / 'session.dpapi'
class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_char))]

def crypt(data: bytes, decrypt=False):
    if os.name != 'nt':
        raise OSError('Windows DPAPI is required for saved Schwab sessions.')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    output = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError('Windows could not unlock the saved Schwab session.')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))

def save(sessions):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    encrypted = crypt(json.dumps(sessions).encode('utf-8'))
    temp = PATH.with_suffix('.tmp')
    try:
        temp.write_bytes(encrypted)
        os.replace(temp, PATH)
    finally:
        temp.unlink(missing_ok=True)

def load():
    if not PATH.exists(): return {}
    result = json.loads(crypt(PATH.read_bytes(), decrypt=True))
    if not isinstance(result, dict): raise ValueError('Invalid saved session')
    return result
