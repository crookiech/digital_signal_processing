import sys
import signal
from gui import *
from PyQt6.QtWidgets import QApplication

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_QSS)

    w = MainWindow()
    w.show()

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    
    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)

    sys.exit(app.exec())