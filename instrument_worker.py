import time
from PyQt6.QtCore import QThread, pyqtSignal

class MeasurementWorker(QThread):
    data_received = pyqtSignal(float, str) 
    error_occurred = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, instrument, interval_ms=100, max_points=10000, infinite=True, skip_repeats=False):
        super().__init__()
        self.instrument = instrument
        self.interval = interval_ms / 1000.0
        self.max_points = max_points
        self.infinite = infinite
        self.skip_repeats = skip_repeats
        self.last_val = None
        self._is_running = True

    def run(self):
        count = 0
        while self._is_running:
            try:
                raw = self.instrument.query('READ?')
                response = raw.strip()
                if not response:
                    raise ValueError(
                        f"READ? вернул пустой ответ: {raw!r}. "
                        "Результат измерения не получен."
                    )
                try:
                    val = float(response)
                except ValueError as exc:
                    raise ValueError(f"READ? вернул нечисловой ответ: {raw!r}") from exc
                
                if self.skip_repeats:
                    if self.last_val is not None and abs(val - self.last_val) < 1e-9:
                        time.sleep(self.interval)
                        continue 
                
                self.last_val = val
                self.data_received.emit(val, "MEAS")
                count += 1

                if not self.infinite and count >= self.max_points:
                    self.finished_signal.emit() 
                    break
                
                time.sleep(self.interval)
            except Exception as e:
                self.error_occurred.emit(f"Ошибка чтения: {e}")
                break

    def stop(self):
        self._is_running = False
        self.wait()
