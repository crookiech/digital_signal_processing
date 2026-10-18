import serial
from PyQt6.QtCore import QObject, pyqtSignal

class SerialWorker(QObject):
    response_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    connected = pyqtSignal(bool, str, int)

    def __init__(self):
        super().__init__()
        self.ser = None
        self._running = False

    def open_port(self, port: str, baud: int = 9600):
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
            self.ser = serial.Serial(
                port=port, baudrate=baud, timeout=0.5,
                write_timeout=0.5, parity=serial.PARITY_NONE,
                bytesize=8, stopbits=1
            )
            self._running = True
            self.connected.emit(True, port, baud)
        except Exception:
            self.ser = None
            self.error_occurred.emit(f"не удалось подключиться к {port}")
            self.connected.emit(False, port, baud)

    def close_port(self):
        self._running = False
        port = self.ser.port if self.ser else ""
        baud = self.ser.baudrate if self.ser else 0
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.connected.emit(False, port, baud)

    def _write(self, cmd: str) -> bool:
        if not self.ser or not self.ser.is_open:
            self.error_occurred.emit("нет подключения")
            return False
        try:
            self.ser.reset_input_buffer()
            self.ser.write((cmd + "\n").encode("ascii"))
            self.ser.flush()
            return True
        except Exception as e:
            self.error_occurred.emit(f"Ошибка записи '{cmd}': {e}")
            return False

    def _query(self, cmd: str) -> str:
        if not self._write(cmd):
            return ""
        try:
            raw = self.ser.readline()
            return raw.decode("ascii", errors="ignore").strip()
        except Exception as e:
            self.error_occurred.emit(f"Ошибка чтения '{cmd}': {e}")
            return ""

    def set_voltage(self, ch: int, v: float):
        self._write(f"CH{ch}:VOLTage {v:.3f}")

    def set_current(self, ch: int, i: float):
        self._write(f"CH{ch}:CURRent {i:.3f}")

    def set_output(self, on: bool):
        self._write(f"OUTPut {'ON' if on else 'OFF'}")

    # def measure(self, ch: int):
    #     v = self._query(f"MEASure:VOLTage? CH{ch}")
    #     i = self._query(f"MEASure:CURRENT? CH{ch}")
    #     try:
    #         vf = float(v) if v else 0.0
    #     except ValueError:
    #         vf = 0.0
    #     try:
    #         if_ = float(i) if i else 0.0
    #     except ValueError:
    #         if_ = 0.0