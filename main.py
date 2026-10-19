import sys
import signal
from gui import *
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from PyQt6.QtCore import QTimer

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 11))
    app.setStyleSheet(GLOBAL_QSS)

    w = MainWindow()
    w.show()

    signal.signal(signal.SIGINT, lambda *_: w.close())

    sig_timer = QTimer()
    sig_timer.start(200)
    sig_timer.timeout.connect(lambda: None)

    sys.exit(app.exec())