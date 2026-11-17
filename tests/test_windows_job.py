import ctypes
import os
import subprocess
import sys
import unittest

from lecture_study.windows_job import BasicLimit,ExtendedLimit


class JobLayoutTests(unittest.TestCase):
    @unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p)==8,'x64 layout')
    def test_win64_job_limit_layout(self):
        self.assertEqual(ctypes.sizeof(BasicLimit),64)
        self.assertEqual(ctypes.sizeof(ExtendedLimit),144)
        self.assertEqual(BasicLimit.Affinity.offset,48)

    @unittest.skipUnless(os.name=='nt','Windows Job Object API required')
    def test_child_cannot_outlive_owned_parent(self):
        script='''
import ctypes,subprocess,sys,time
from lecture_study.windows_job import own_process_tree
job=own_process_tree()
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
print(child.pid,flush=True)
time.sleep(60)
'''
        owner=subprocess.Popen([sys.executable,'-c',script],stdout=subprocess.PIPE,text=True)
        self.addCleanup(lambda:owner.kill() if owner.poll() is None else None)
        pid=int(owner.stdout.readline().strip())
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32];kernel.WaitForSingleObject.restype=ctypes.c_uint32
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        child=kernel.OpenProcess(0x100000,False,pid)
        self.assertTrue(child)
        try:
            owner.kill();owner.wait(timeout=5)
            self.assertEqual(kernel.WaitForSingleObject(child,5000),0)
        finally:kernel.CloseHandle(child)


if __name__=='__main__':unittest.main()
