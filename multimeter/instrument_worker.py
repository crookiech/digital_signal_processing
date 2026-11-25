import time
import threading
from contextlib import contextmanager
from PyQt6.QtCore import QThread, pyqtSignal

class MeasurementWorker(QThread):
    data_received = pyqtSignal(float, str) 
    error_occurred = pyqtSignal(str)
    measurement_error = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, instrument, interval_ms=100, max_points=10000, infinite=True, skip_repeats=False,
                 function="MEAS"):
        super().__init__()
        self.instrument = instrument
        self.interval = interval_ms / 1000.0
        self.max_points = max_points
        self.infinite = infinite
        self.skip_repeats = skip_repeats
        self.last_val = None
        self._is_running = True
        self.function = function
        self._io_lock = threading.RLock()
        self._configuration_depth = 0
        self._ready_at = 0.0
        self._stopped = threading.Event()
        self._invalid_replies = 0

    @contextmanager
    def configuration(self):
        """Finish the current read, then keep the whole settings batch together."""
        with self._io_lock:
            self._configuration_depth += 1
            try:
                yield
            finally:
                self._configuration_depth -= 1
                if self._configuration_depth == 0:
                    self.last_val = None
                    self._invalid_replies = 0
                    self._ready_at = time.monotonic() + 0.25

    def run(self):
        count = 0
        while self._is_running:
            try:
                with self._io_lock:
                    if not self._is_running:
                        break
                    remaining = self._ready_at - time.monotonic()
                    if remaining <= 0:
                        raw = self.instrument.query('READ?')
                        response = raw.strip()
                        if not response:
                            self._invalid_replies += 1
                            if self._invalid_replies >= 3:
                                self.measurement_error.emit(
                                    f"READ? вернул пустой ответ: {raw!r}. "
                                    "Результат измерения не получен после 3 попыток."
                                )
                                break
                        else:
                            try:
                                val = float(response)
                            except ValueError:
                                self.measurement_error.emit(
                                    f"READ? вернул нечисловой ответ: {raw!r}"
                                )
                                break
                            self._invalid_replies = 0
                            repeated = (
                                self.skip_repeats and self.last_val is not None
                                and abs(val - self.last_val) < 1e-9
                            )
                            if not repeated:
                                self.last_val = val
                                self.data_received.emit(val, self.function)
                                count += 1
                                if not self.infinite and count >= self.max_points:
                                    self.finished_signal.emit()
                                    break
                if remaining > 0:
                    self._stopped.wait(min(remaining, 0.05))
                    continue
                if not response:
                    self._stopped.wait(max(self.interval, 0.1))
                else:
                    self._stopped.wait(self.interval)
            except Exception as e:
                self.error_occurred.emit(f"Ошибка чтения: {e}")
                break

    def stop(self):
        self._is_running = False
        self._stopped.set()
        self.wait()
