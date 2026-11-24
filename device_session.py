from PyQt6.QtCore import QObject, QThread, pyqtSignal
from serial_worker import SerialWorker
from device_model import DeviceState

class DeviceSession(QObject):
    connected = pyqtSignal(str, bool, str)
    response = pyqtSignal(str, str)
    error = pyqtSignal(str, str)

    sig_open = pyqtSignal(str, int)
    sig_close = pyqtSignal()
    sig_set_v = pyqtSignal(int, float)
    sig_set_i = pyqtSignal(int, float)
    sig_set_out = pyqtSignal(bool)
    sig_get_v = pyqtSignal(int)
    sig_get_i = pyqtSignal(int)
    sig_get_sn = pyqtSignal()

    def __init__(self, state: DeviceState, parent=None):
        super().__init__(parent)
        self.state = state
        self.sid = state.session_id

        self.thread = QThread()
        self.worker = SerialWorker()
        self.worker.moveToThread(self.thread)

        self.sig_open.connect(self.worker.open_port)
        self.sig_close.connect(self.worker.close_port)
        self.sig_set_v.connect(self.worker.set_voltage)
        self.sig_set_i.connect(self.worker.set_current)
        self.sig_set_out.connect(self.worker.set_output)
        self.sig_get_v.connect(self.worker.get_voltage)
        self.sig_get_i.connect(self.worker.get_current)
        self.sig_get_sn.connect(self.worker.get_serial_number)

        self.worker.connected.connect(lambda ok, port: self.connected.emit(self.sid, ok, port))
        self.worker.response_received.connect(lambda msg: self.response.emit(self.sid, msg))
        self.worker.error_occurred.connect(lambda msg: self.error.emit(self.sid, msg))

        self.thread.start()

    def open(self):
        self.sig_open.emit(self.state.port, self.state.baud)

    def close(self):
        self.sig_close.emit()

    def set_voltage(self, ch: int, v: float):
        self.sig_set_v.emit(ch, v)

    def set_current(self, ch: int, i: float):
        self.sig_set_i.emit(ch, i)

    def set_output(self, on: bool):
        self.sig_set_out.emit(on)

    def request_voltage(self, ch: int):
        self.sig_get_v.emit(ch)

    def request_current(self, ch: int):
        self.sig_get_i.emit(ch)

    def request_sn(self):
        self.sig_get_sn.emit()

    def shutdown(self):
        try:
            self.worker.connected.disconnect()
            self.worker.response_received.disconnect()
            self.worker.error_occurred.disconnect()
        except TypeError:
            pass
        self.sig_close.emit()
        self.thread.quit()
        self.thread.wait(1000)