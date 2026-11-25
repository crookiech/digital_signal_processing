import pyvisa
import time
from PyQt6.QtCore import QObject, pyqtSignal

VI_ATTR_ASRL_BAUD = 0x3FFF0001
VI_ATTR_ASRL_DATA_BITS = 0x3FFF0002
VI_ATTR_ASRL_PARITY = 0x3FFF0006
VI_ATTR_ASRL_STOP_BITS = 0x3FFF0003
VI_ATTR_ASRL_FLOW_CNTRL = 0x3FFF0005
VI_ASRL_PAR_NONE = 0
VI_ASRL_STOP_ONE = 10
VI_ASRL_FLOW_NONE = 16

class SerialWorker(QObject):
    response_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    connected = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        self.rm = None
        self.instr = None

    def _get_rm(self):
        if self.rm is None:
            try:
                self.rm = pyvisa.ResourceManager('@ivi')
            except Exception:
                self.rm = pyvisa.ResourceManager('@py')
        return self.rm

    def open_port(self, port: str, baud: int = 0):
        try:
            rm = self._get_rm()
            self.instr = rm.open_resource(port)

            is_serial = port.upper().startswith("ASRL")
            if is_serial:
                if baud <= 0:
                    baud = 9600
                try:
                    self.instr.set_visa_attribute(VI_ATTR_ASRL_BAUD, int(baud))
                    self.instr.set_visa_attribute(VI_ATTR_ASRL_DATA_BITS, 8)
                    self.instr.set_visa_attribute(VI_ATTR_ASRL_PARITY, VI_ASRL_PAR_NONE)
                    self.instr.set_visa_attribute(VI_ATTR_ASRL_STOP_BITS, VI_ASRL_STOP_ONE)
                    self.instr.set_visa_attribute(VI_ATTR_ASRL_FLOW_CNTRL, VI_ASRL_FLOW_NONE)
                except Exception:
                    if baud:
                        try:
                            self.instr.baud_rate = int(baud)
                        except Exception:
                            pass

            self.instr.timeout = 5000
            self.instr.read_termination = '\n'
            self.instr.write_termination = '\n'
            self.connected.emit(True, port)
        except Exception as e:
            self.instr = None
            self.error_occurred.emit(f"не удалось подключиться к {port}: {e}")
            self.connected.emit(False, port)

    def close_port(self):
        port = ""
        try:
            if self.instr:
                port = self.instr.resource_name
                self.instr.close()
                self.instr = None
        except Exception:
            pass
        self.connected.emit(False, port)

    def _write(self, cmd: str) -> bool:
        if not self.instr:
            self.error_occurred.emit("нет подключения")
            return False
        try:
            self.instr.write(cmd)
            return True
        except Exception as e:
            self.error_occurred.emit(f"Ошибка записи '{cmd}': {e}")
            return False

    def _query(self, cmd: str) -> str:
        print(f"[QUERY] {cmd}")
        if not self.instr:
            self.error_occurred.emit("нет подключения")
            return ""
        try:
            # Очищаем буфер приема и отправляем команду
            self.instr.clear()
            self.instr.write(cmd)
            time.sleep(0.2)  # даем прибору время подумать
            return self.instr.read().strip()
        except Exception as e:
            self.error_occurred.emit(f"Ошибка чтения '{cmd}': {e}")
            return ""

    def set_voltage(self, ch: int, v: float):
        self._write(f"CH{ch}:VOLTage {v:.3f}")

    def set_current(self, ch: int, i: float):
        self._write(f"CH{ch}:CURRent {i:.3f}")

    def set_output(self, on: bool):
        self._write(f"OUTPUT {'ON' if on else 'OFF'}")

    def get_voltage(self, ch: int):
        voltage = self._query(f"CH{ch}:VOLTage?")
        print(f"[DEBUG] CH{ch} voltage response: '{voltage}'")
        if voltage:
            self.response_received.emit(f"VOLTAGE:{ch}:{voltage}")

    def get_current(self, ch: int):
        if ch == 3:
            self._write("INStrument CH3")
            time.sleep(0.05)
            current = self._query("CURRent?")
        else:
            current = self._query(f"CH{ch}:CURRent?")
        print(f"[DEBUG] CH{ch} current response: '{current}'")
        if current:
            self.response_received.emit(f"CURRENT:{ch}:{current}")

    def get_serial_number(self):
        print(">>> Отправка *IDN?")
        raw = self._query("*IDN?")
        print("<<< Ответ:", raw)
        parts = [p.strip() for p in raw.split(",")] if raw else []
        serial_number = parts[2] if len(parts) >= 3 else (raw or "")
        self.response_received.emit(f"SERIAL_NUMBER:{serial_number}")