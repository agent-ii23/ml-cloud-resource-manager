"""Current-Windows-user encrypted, demo-only credentials. Never log secrets."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path

import boto3

SECRET_PATH = Path(__file__).resolve().parent.parent / '.secrets' / 'cloud-ml.dpapi'


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, decrypt=False):
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    dll = ctypes.windll.crypt32
    fn = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    ok = fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.windll.kernel32.LocalFree(result.data)


def demo_session():
    if SECRET_PATH.exists():
        values = json.loads(crypt(SECRET_PATH.read_bytes(), decrypt=True))
        return boto3.Session(aws_access_key_id=values['id'], aws_secret_access_key=values['secret'], region_name='ap-southeast-2')
    return boto3.Session(region_name='ap-southeast-2')


if __name__ == '__main__':
    import csv
    import sys
    with open(sys.argv[1], newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 1 or 'Access key ID' not in rows[0] or 'Secret access key' not in rows[0]:
        raise SystemExit('Unexpected credential CSV format; no credentials printed.')
    data = json.dumps({'id': rows[0]['Access key ID'], 'secret': rows[0]['Secret access key']}).encode()
    SECRET_PATH.parent.mkdir(exist_ok=True)
    SECRET_PATH.write_bytes(crypt(data))
    print('Demo credentials encrypted for the current Windows user. Secret values were not printed.')
