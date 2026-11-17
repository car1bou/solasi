"""Own Windows worker descendants without depending on process-name matching."""
import ctypes
import os


class BasicLimit(ctypes.Structure):
    _fields_=[('ProcessUserTimeLimit',ctypes.c_int64),('JobUserTimeLimit',ctypes.c_int64),('LimitFlags',ctypes.c_uint32),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',ctypes.c_uint32),('Affinity',ctypes.c_size_t),('PriorityClass',ctypes.c_uint32),('SchedulingClass',ctypes.c_uint32)]


class IOCounters(ctypes.Structure):
    _fields_=[(name,ctypes.c_uint64) for name in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]


class ExtendedLimit(ctypes.Structure):
    _fields_=[('BasicLimitInformation',BasicLimit),('IoInfo',IOCounters),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]


def own_process_tree():
    if os.name!='nt':raise ValueError('Windows Job Object는 Windows에서만 사용할 수 있습니다')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p];kernel.CreateJobObjectW.restype=ctypes.c_void_p
    kernel.SetInformationJobObject.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32];kernel.SetInformationJobObject.restype=ctypes.c_int
    kernel.AssignProcessToJobObject.argtypes=[ctypes.c_void_p,ctypes.c_void_p];kernel.AssignProcessToJobObject.restype=ctypes.c_int
    kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle.restype=ctypes.c_int
    handle=kernel.CreateJobObjectW(None,None)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    limits=ExtendedLimit();limits.BasicLimitInformation.LimitFlags=0x2000
    if not kernel.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
        error=ctypes.get_last_error();kernel.CloseHandle(handle);raise ctypes.WinError(error)
    if not kernel.AssignProcessToJobObject(handle,kernel.GetCurrentProcess()):
        error=ctypes.get_last_error();kernel.CloseHandle(handle);raise ctypes.WinError(error)
    return handle
