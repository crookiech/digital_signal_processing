"""Run network configuration and VISA identification outside the GUI thread."""
import os
import subprocess
import sys
from PyQt6.QtCore import QThread, pyqtSignal


class OperationWorker(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            result = self.operation()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)


def prepare_lan(configurator, guid):
    from scapy.all import conf
    from scapy.arch.windows import get_windows_if_list

    if not conf.use_pcap:
        installer_name = "npcap-installer.exe"
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        installer_path = os.path.join(base_path, "drivers", installer_name)

        if os.path.exists(installer_path):
            try:
                subprocess.Popen(f'powershell Start-Process "{installer_path}" -Verb RunAs', shell=True)
                raise RuntimeError(
                    "Драйвер Npcap не обнаружен в системе.\n\n"
                    "Запущен локальный установщик из папки проекта. "
                    "Установите Npcap (обязательно включите WinPcap-совместимость), затем перезапустите программу."
                )
            except Exception as e:
                raise RuntimeError(f"Не удалось автоматически запустить установщик Npcap: {e}")
        else:
            raise RuntimeError(
                "Для DHCP требуется Npcap. Установщик не найден в папке проекта.\n"
                "Скачайте и установите Npcap с сайта npcap.com"
            )

    normalize = lambda value: str(value or "").strip("{}").lower()
    interface = next((item for item in get_windows_if_list()
                      if normalize(item.get("guid")) == normalize(guid)), None)
    if interface is None:
        raise RuntimeError("Npcap не видит выбранный Ethernet. Обновите адаптеры.")
        
    plan = configurator.prepare(guid)
    plan["capture_interface"] = interface.get("network_name") or rf"\Device\NPF_{guid}"
    return plan


def open_instrument(resource_manager, resource_name, require_ut8805e=False):
    instrument = None
    try:
        instrument = resource_manager.open_resource(resource_name, open_timeout=5000)
        instrument.timeout = 5000
        # USBTMC supplies an end-of-message marker. A newline terminator can
        # leave the rest of that USB message for the next query to consume.
        is_usbtmc = resource_name.upper().startswith("USB") and resource_name.upper().endswith("::INSTR")
        instrument.read_termination = None if is_usbtmc else "\n"
        instrument.write_termination = "\n"
        identity = instrument.query("*IDN?").strip()
        if not identity:
            raise ValueError("Прибор не ответил на *IDN?.")
        # This instrument's firmware reports UT8805 without the E suffix.
        fields = [field.strip().upper() for field in identity.split(",")]
        model = fields[1] if len(fields) > 1 else ""
        if require_ut8805e and model not in {"UT8805", "UT8805E"}:
            raise ValueError(f"По этому адресу найден другой прибор: {identity}")
        # No measurement configuration is sent until identity has been checked.
        instrument.write("CONF:VOLT:DC")
        instrument.write("VOLT:DC:RANG:AUTO ON")
        instrument.write("VOLT:DC:IMP:AUTO ON")
        return instrument, identity
    except Exception:
        if instrument is not None:
            try:
                instrument.close()
            except Exception:
                pass
        raise
