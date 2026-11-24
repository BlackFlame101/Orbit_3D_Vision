"""Tie spawned inference and texture subprocesses to the Windows worker lifetime."""
import ctypes
import os
from ctypes import wintypes


def contain_children():
    if os.name!='nt':return
    class Limits(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',wintypes.DWORD),
                  ('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active',wintypes.DWORD),
                  ('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
    class Extended(ctypes.Structure):
        _fields_=[('basic',Limits),('io',ctypes.c_ulonglong*6),('memory',ctypes.c_size_t*4)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype=wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    job=kernel.CreateJobObjectW(None,None)
    if not job:raise ctypes.WinError(ctypes.get_last_error())
    limits=Extended()
    limits.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not (kernel.SetInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits))
            and kernel.AssignProcessToJobObject(job,kernel.GetCurrentProcess())):
        error=ctypes.get_last_error()
        kernel.CloseHandle(job)
        raise ctypes.WinError(error)
    # Non-inheritable handle stays open in this worker until the OS closes it at exit.
