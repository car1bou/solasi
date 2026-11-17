"""Per-vault WM_COPYDATA handoff for exported audio links; no network listener."""
import ctypes
import hashlib
import logging
import os
from pathlib import Path

TAG=0x534f4c41
WM_COPYDATA=0x004a


class CopyData(ctypes.Structure):
    _fields_=[('dwData',ctypes.c_size_t),('cbData',ctypes.c_uint32),('lpData',ctypes.c_void_p)]


def instance_key(data_dir):
    path=os.path.normcase(str(Path(data_dir).resolve()))
    return 'Solasi.Instance.'+hashlib.sha256(path.encode()).hexdigest()[:24]


def decode_link(data):
    if not 2<=len(data)<=16386 or len(data)%2:raise ValueError('원음 링크 메시지 크기를 확인하세요')
    try:url=data.decode('utf-16-le')
    except UnicodeError:raise ValueError('원음 링크 메시지 인코딩을 확인하세요') from None
    if not url.endswith('\0'):raise ValueError('원음 링크 메시지가 끝나지 않았습니다')
    url=url[:-1]
    if not url.startswith('solasi://audio/') or any(ord(c)<32 for c in url):raise ValueError('원음 링크를 확인하세요')
    return url


def user32():
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.GetPropW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p];user.GetPropW.restype=ctypes.c_void_p
    user.SetPropW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_void_p];user.SetPropW.restype=ctypes.c_int
    user.RemovePropW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p];user.RemovePropW.restype=ctypes.c_void_p
    user.SetWindowLongPtrW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p];user.SetWindowLongPtrW.restype=ctypes.c_void_p
    user.CallWindowProcW.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_size_t,ctypes.c_ssize_t];user.CallWindowProcW.restype=ctypes.c_ssize_t
    return user


def send_audio_link(data_dir,url):
    if os.name!='nt':return False
    payload=(url+'\0').encode('utf-16-le');decode_link(payload)
    user=user32();key=instance_key(data_dir);found=[]
    callback_type=ctypes.WINFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_ssize_t)
    @callback_type
    def inspect(hwnd,_):
        if user.GetPropW(hwnd,key):found.append(hwnd);return 0
        return 1
    user.EnumWindows.argtypes=[callback_type,ctypes.c_ssize_t];user.EnumWindows.restype=ctypes.c_int
    user.EnumWindows(inspect,0)
    if not found:return False
    data=ctypes.create_string_buffer(payload);copy=CopyData(TAG,len(payload),ctypes.cast(data,ctypes.c_void_p))
    user.SendMessageTimeoutW.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.POINTER(ctypes.c_size_t)];user.SendMessageTimeoutW.restype=ctypes.c_ssize_t
    result=ctypes.c_size_t()
    sent=user.SendMessageTimeoutW(found[0],WM_COPYDATA,0,ctypes.byref(copy),2,1500,ctypes.byref(result))
    return bool(sent and result.value==1)


class Receiver:
    def __init__(self,hwnd,data_dir,receive):
        self.user=user32();self.hwnd=hwnd;self.key=instance_key(data_dir);self.original=None
        callback_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_size_t,ctypes.c_ssize_t)
        @callback_type
        def procedure(window,message,wparam,lparam):
            if message==WM_COPYDATA:
                try:
                    if not lparam:return 0
                    copy=ctypes.cast(lparam,ctypes.POINTER(CopyData)).contents
                    if copy.dwData!=TAG or not copy.lpData or not 2<=copy.cbData<=16386:return 0
                    receive(decode_link(ctypes.string_at(copy.lpData,copy.cbData)));return 1
                except Exception:logging.exception('Rejected audio link handoff');return 0
            return self.user.CallWindowProcW(self.original,window,message,wparam,lparam)
        self.procedure=procedure
        ctypes.set_last_error(0)
        self.original=self.user.SetWindowLongPtrW(hwnd,-4,ctypes.cast(procedure,ctypes.c_void_p))
        if not self.original:raise ctypes.WinError(ctypes.get_last_error())
        if not self.user.SetPropW(hwnd,self.key,1):
            error=ctypes.get_last_error();self.close();raise ctypes.WinError(error)

    def close(self):
        self.user.RemovePropW(self.hwnd,self.key)
        if self.original:
            self.user.SetWindowLongPtrW(self.hwnd,-4,self.original);self.original=None
