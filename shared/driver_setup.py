"""Check bundled Windows driver prerequisites before creating device windows."""

import ctypes
import os
import sys
from dataclasses import dataclass

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QDialog, QLabel, QMessageBox, QProgressBar, QVBoxLayout

from .driver_installers import find_installer, install_and_wait


@dataclass(frozen=True)
class DriverStatus:
    ready: bool
    detail: str = ""


@dataclass(frozen=True)
class SetupResult:
    ready: bool
    message: str = ""
    restart_required: bool = False


DRIVERS = (
    ("visa", "VISA (установщик NI-VISA)", "ni-visa-installer.exe"),
    ("npcap", "Npcap", "npcap-installer.exe"),
)


def check_visa():
    # @py is a Python package, not evidence of an installed system VISA runtime.
    import pyvisa
    try:
        manager = pyvisa.ResourceManager("@ivi")
        manager.close()
    except Exception as exc:
        return DriverStatus(False, str(exc))
    return DriverStatus(True)


def check_npcap():
    # Avoid importing scapy.all here: it enumerates capture interfaces and can
    # block with an administrator-only Npcap installation.
    import winreg
    from ctypes import wintypes

    service_found = False
    for service in ("npcap", "npf"):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                rf"SYSTEM\CurrentControlSet\Services\{service}",
            ):
                service_found = True
                break
        except FileNotFoundError:
            pass
    if not service_found:
        return DriverStatus(False, "Служба драйвера Npcap не найдена.")

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    kernel.GetSystemDirectoryW.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < length < len(buffer):
        return DriverStatus(False, "Не удалось найти системную папку Windows.")

    from pathlib import Path
    system = Path(buffer.value)
    errors = []
    for directory in (system / "Npcap", system):
        library = directory / "wpcap.dll"
        if not library.is_file():
            continue
        try:
            # Explicit architecture-appropriate system path, including Packet.dll.
            with os.add_dll_directory(str(directory)):
                pcap = ctypes.CDLL(str(library))
                pcap.pcap_lib_version.argtypes = []
                pcap.pcap_lib_version.restype = ctypes.c_char_p
                version = pcap.pcap_lib_version() or b""
            if version.lower().strip().startswith(b"npcap "):
                return DriverStatus(True)
            errors.append("Найдена библиотека захвата, но это не Npcap.")
        except OSError as exc:
            errors.append(str(exc))
    return DriverStatus(False, "; ".join(errors) or "Библиотека Npcap не найдена.")


def check_driver(key):
    try:
        return {"visa": check_visa, "npcap": check_npcap}[key]()
    except Exception as exc:
        return DriverStatus(False, str(exc))


def installer_problem(filename):
    installer = find_installer(filename)
    if installer is None:
        return f"Не найден drivers/{filename}. Склонируйте репозиторий с папкой drivers."
    if filename == "ni-visa-installer.exe":
        for relative in ("ni-visa-installer.ini", "Products", "SupportFiles"):
            if not (installer.parent / relative).exists():
                return (
                    f"Неполный комплект NI-VISA: отсутствует drivers/{relative}. "
                    "Нужна вся папка drivers, а не только exe-файл."
                )
    return ""


def prepare_drivers(progress=lambda message: None):
    """No device polling, packet capture, or application windows during setup."""
    if sys.platform != "win32":
        return SetupResult(True)
    for key, label, filename in DRIVERS:
        progress(f"Проверка {label}…")
        before = check_driver(key)
        if before.ready:
            continue
        problem = installer_problem(filename)
        if problem:
            return SetupResult(False, f"{label} недоступен.\n{problem}\n\n{before.detail}")
        progress(
            f"Установка {label}.\n"
            "Подтвердите запрос Windows на права администратора "
            "и завершите установку в открывшемся окне.\n"
            "Приложение дождётся завершения установщика."
        )
        try:
            code = install_and_wait(filename)
        except Exception as exc:
            return SetupResult(False, f"Установка {label} не завершена.\n{exc}")
        if code in (3010, 1641):
            return SetupResult(False, (
                f"Установщик {label} сообщил о необходимости перезагрузки Windows.\n"
                "После перезагрузки снова выполните python main.py. "
                "Уже доступные драйверы повторно устанавливаться не будут."
            ), restart_required=True)
        if code != 0:
            return SetupResult(False, (
                f"Установщик {label} завершился с кодом {code}.\n"
                "Установка могла быть отменена или закончиться ошибкой. "
                "После устранения причины снова запустите приложение."
            ))
        progress(f"Повторная проверка {label} после установки…")
        after = check_driver(key)
        if not after.ready:
            return SetupResult(False, (
                f"Установщик {label} завершился, но драйвер пока недоступен.\n"
                f"{after.detail}\n\n"
                "Проверьте результат в установщике. Если он требует перезагрузки, "
                "перезагрузите Windows, затем снова выполните python main.py."
            ))
    return SetupResult(True)


class DriverSetupWorker(QThread):
    progress = pyqtSignal(str)
    completed = pyqtSignal(object)

    def run(self):
        try:
            result = prepare_drivers(self.progress.emit)
        except Exception as exc:
            result = SetupResult(False, f"Ошибка подготовки драйверов: {exc}")
        self.completed.emit(result)


class DriverSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Подготовка измерительной системы")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        self.label = QLabel("Проверка системных драйверов…")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        progress = QProgressBar()
        progress.setRange(0, 0)
        layout.addWidget(progress)
        self.setup_result = SetupResult(False, "Проверка драйверов не завершена.")
        self._complete = False
        self.worker = DriverSetupWorker(self)
        self.worker.progress.connect(self.label.setText)
        self.worker.completed.connect(self._store_result)
        # Never destroy a running QThread when its result arrives.
        self.worker.finished.connect(self._finished)

    def _store_result(self, result):
        self.setup_result = result

    def _finished(self):
        self._complete = True
        self.accept()

    def reject(self):
        # Cancellation happens in the actual installer; keep its process owned
        # and report its result instead of launching an application alongside it.
        if self._complete:
            super().reject()

    def closeEvent(self, event):
        if not self._complete:
            event.ignore()
        else:
            super().closeEvent(event)


def ensure_system_drivers(parent=None):
    if sys.platform != "win32":
        return True
    dialog = DriverSetupDialog(parent)
    QTimer.singleShot(0, dialog.worker.start)
    dialog.exec()
    if not dialog.setup_result.ready:
        show = QMessageBox.information if dialog.setup_result.restart_required else QMessageBox.critical
        show(parent, "Подготовка драйверов", dialog.setup_result.message)
    return dialog.setup_result.ready
