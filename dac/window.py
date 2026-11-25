"""DAC/ADC window adapter; replace the placeholder with the existing PyQt6 GUI."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget


class DacWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.shutdown_complete = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowTitle("ЦАП/АЦП — модуль в разработке")
        self.resize(760, 480)

        content = QWidget(self)
        layout = QVBoxLayout(content)
        message = QLabel(
            "Модуль ЦАП/АЦП в разработке.\n"
            "Здесь будет интерфейс управления устройством.",
            content,
        )
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setWordWrap(True)
        layout.addWidget(message)
        self.setCentralWidget(content)

    def closeEvent(self, event):
        # The session manager owns this window. Closing it only hides the view.
        event.accept()

    def advance_shutdown(self):
        """Stop device work before returning True; see README.md for integration."""
        if self.shutdown_complete:
            return True
        # TODO: request worker shutdown and return False while I/O is still running.
        self.shutdown_complete = True
        self.close()
        return True

    def resource_managers(self):
        """Return owned VISA managers once the module uses them."""
        return ()

    def release_manager_references(self):
        """Clear VISA manager references after SessionManager has closed them."""
        pass
