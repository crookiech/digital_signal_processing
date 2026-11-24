# Тестовый запуск модуля отдельно от внешнего главного окна.
import sys
import signal
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from PyQt6.QtCore import QTimer
from styles import GLOBAL_QSS
from power_supply import PowerSupplyController

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 11))
    app.setStyleSheet(GLOBAL_QSS)

    ctrl = PowerSupplyController()
    ctrl.error.connect(lambda sid, msg: print(f"[{sid}] {msg}"))
    ctrl.add_device("psu1")
    ctrl.open_settings_window("psu1")

    app.aboutToQuit.connect(ctrl.shutdown_all)
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    sig_timer = QTimer()
    sig_timer.start(200)
    sig_timer.timeout.connect(lambda: None)

    sys.exit(app.exec())
