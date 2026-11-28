"""Resolve the existing driver distribution independently of the working directory."""

import ctypes
import sys
from pathlib import Path


def find_installer(name):
    roots = []
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(sys._MEIPASS))
    package = Path(__file__).resolve().parents[1]
    roots.extend((package, package.parent))
    for root in roots:
        installer = root / "drivers" / name
        if installer.is_file():
            return installer
    return None


def launch_installer(name):
    installer = find_installer(name)
    if installer is None:
        return False
    if sys.platform != "win32":
        raise RuntimeError("Установщик драйвера рассчитан на Windows.")
    # Pass paths directly to Windows; spaces and Cyrillic do not need shell quoting.
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(installer), None, str(installer.parent), 1
    )
    if result <= 32:
        raise RuntimeError(
            f"Не удалось запустить {name} (код Windows: {result}). "
            "Установка могла быть отменена."
        )
    return True


def _windows_libraries():
    from ctypes import wintypes
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    return shell, kernel, ole


def install_and_wait(name):
    """Run a visible elevated installer and wait; call from a worker thread."""
    from ctypes import wintypes
    installer = find_installer(name)
    if installer is None:
        raise RuntimeError(f"Установщик drivers/{name} не найден.")
    if sys.platform != "win32":
        raise RuntimeError("Установщик драйвера рассчитан на Windows.")

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.DWORD),
            ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell, kernel, ole = _windows_libraries()
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    initialized = ole.CoInitializeEx(None, 2) >= 0
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    # Keep the process handle and finish shell dispatch before waiting.
    info.fMask = 0x00000040 | 0x00000100
    info.lpVerb = "runas"
    info.lpFile = str(installer)
    info.lpDirectory = str(installer.parent)
    info.nShow = 1
    try:
        if not shell.ShellExecuteExW(ctypes.byref(info)):
            code = ctypes.get_last_error()
            if code == 1223:
                raise RuntimeError("Установка отменена в запросе прав администратора Windows.")
            raise RuntimeError(f"Не удалось запустить {name}: ошибка Windows {code}.")
        if not info.hProcess:
            raise RuntimeError(f"Windows не вернула процесс установщика {name}.")
        try:
            if kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF) != 0:
                raise RuntimeError(f"Не удалось дождаться завершения {name}.")
            exit_code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
                raise RuntimeError(f"Не удалось получить результат установки {name}.")
            return exit_code.value
        finally:
            kernel.CloseHandle(info.hProcess)
    finally:
        if initialized:
            ole.CoUninitialize()
