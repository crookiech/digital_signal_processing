import pyvisa
from PyQt6.QtCore import QObject, pyqtSignal

class SerialWorker(QObject):
    response_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    connected = pyqtSignal(bool, str)
    connection_lost = pyqtSignal(str) 

    def __init__(self):
        super().__init__()
        self.rm = None
        self.instr = None
        self._running = False

    def open_port(self, port: str, baud: int = 0):
        try:
            if self.rm is None:
                try:
                    self.rm = pyvisa.ResourceManager('@ivi')
                except Exception:
                    self.rm = pyvisa.ResourceManager('@py')
            self.instr = self.rm.open_resource(port)
            self.instr.timeout = 5000
            self.instr.read_termination = '\n'
            self.instr.write_termination = '\n'
            self._running = True
            self.connected.emit(True, port)
        except Exception as e:
            self.instr = None
            self.error_occurred.emit(f"не удалось подключиться к {port}: {e}")
            self.connected.emit(False, port)

    def close_port(self):
        self._running = False
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
        if not self.instr:
            self.error_occurred.emit("нет подключения")
            return ""
        try:
            return self.instr.query(cmd).strip()
        except Exception as e:
            self.error_occurred.emit(f"Ошибка чтения '{cmd}': {e}")
            return ""

    def set_voltage(self, ch: int, v: float):
        self._write(f"CH{ch}:VOLTage {v:.3f}")

    def set_current(self, ch: int, i: float):
        self._write(f"CH{ch}:CURRent {i:.3f}")

    def set_output(self, on: bool):
        self._write(f"OUTPUT {'ON' if on else 'OFF'}")