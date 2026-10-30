"""Launch external tools without inheriting the frozen application's DLL search path."""
import os
import subprocess
import sys
from threading import RLock

_LAUNCH_LOCK = RLock()


def external_environment():
    result = os.environ.copy()
    if getattr(sys, 'frozen', False):
        root = os.path.normcase(os.path.abspath(getattr(sys, '_MEIPASS', '')))
        result['PATH'] = os.pathsep.join(p for p in result.get('PATH', '').split(os.pathsep)
            if not root or not os.path.normcase(os.path.abspath(p)).startswith(root + os.sep)
            and os.path.normcase(os.path.abspath(p)) != root)
        if os.name != 'nt':
            original = result.get('LD_LIBRARY_PATH_ORIG')
            if original is None: result.pop('LD_LIBRARY_PATH', None)
            else: result['LD_LIBRARY_PATH'] = original
    return result


def external_popen(args, **kwargs):
    kwargs.setdefault('env', external_environment())
    with _LAUNCH_LOCK:
        if os.name != 'nt' or not getattr(sys, 'frozen', False):
            return subprocess.Popen(args, **kwargs)
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
        kernel.GetDllDirectoryW.restype = ctypes.c_uint32
        kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        kernel.SetDllDirectoryW.restype = ctypes.c_int
        length = kernel.GetDllDirectoryW(0, None)
        buffer = ctypes.create_unicode_buffer(length + 1)
        kernel.GetDllDirectoryW(len(buffer), buffer)
        previous = buffer.value
        if not kernel.SetDllDirectoryW(None):
            raise OSError(ctypes.get_last_error(), '외부 프로그램 DLL 검색 경로 초기화 실패')
        try:
            return subprocess.Popen(args, **kwargs)
        finally:
            if not kernel.SetDllDirectoryW(previous or None):
                raise OSError(ctypes.get_last_error(), '앱 DLL 검색 경로 복원 실패')


def external_run(args, timeout=15):
    process = external_popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             encoding='utf-8', errors='replace')
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def startup_failure(returncode):
    return returncode is not None and (returncode & 0xFFFFFFFF) == 0xC0000142
