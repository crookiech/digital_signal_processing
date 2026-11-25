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
