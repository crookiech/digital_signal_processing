import pyvisa
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QGroupBox, QFormLayout, QHBoxLayout, QComboBox, QPushButton, QMessageBox)

class ConnectionPanel(QGroupBox):
    connect_requested = pyqtSignal(str, str, int)
    log = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Подключение", parent)
        self._busy_ports: set[str] = set()

        self.rm = None
        try:
            self.rm = pyvisa.ResourceManager('@ivi')
        except Exception:
            try:
                self.rm = pyvisa.ResourceManager('@py')
            except Exception as e:
                print(f"VISA не инициализирован: {e}")

        layout = QFormLayout(self)
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(10)
        self._layout = layout

        self.cmb_iface = QComboBox()
        self.cmb_iface.addItem("USB", "USB")
        self.cmb_iface.addItem("RS232", "ASRL")
        layout.addRow("Интерфейс:", self.cmb_iface)

        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        btn_refresh = QPushButton("Обновить")
        btn_refresh.clicked.connect(self.refresh_ports)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(btn_refresh)
        layout.addRow("Порт:", port_row)

        self.baud_row = QHBoxLayout()
        self.baud_combo = QComboBox()
        for b in (9600, 19200, 38400, 57600, 115200):
            self.baud_combo.addItem(str(b), b)
        self.baud_combo.setCurrentText("9600")
        self.baud_row.addWidget(self.baud_combo, 1)
        layout.addRow("Бод:", self.baud_row)

        self.btn_connect = QPushButton("Подключить")
        self.btn_connect.clicked.connect(self._on_connect_clicked)
        layout.addRow(self.btn_connect)

        self.cmb_iface.currentIndexChanged.connect(self._on_iface_changed)
        self._on_iface_changed()

    def set_busy_ports(self, ports: set[str]):
        self._busy_ports = set(ports)
        self.refresh_ports()

    def _on_iface_changed(self):
        is_serial = self.cmb_iface.currentData() == "ASRL"
        self._layout.setRowVisible(self.baud_row, is_serial)
        self.refresh_ports()

    def refresh_ports(self):
        iface = self.cmb_iface.currentData()
        self.log.emit("Обновление портов...")
        self.port_combo.clear()

        if not self.rm:
            self.port_combo.addItem("VISA не инициализирован", None)
            return
        try:
            resources = self.rm.list_resources()
        except Exception as e:
            print(f"Ошибка поиска ресурсов: {e}")
            self.port_combo.addItem("Ошибка поиска", None)
            return

        if iface == "USB":
            filtered = [r for r in resources if 'USB' in r and 'INSTR' in r]
            empty_text = "Нет USB-инструментов"
        else:
            filtered = [r for r in resources if r.upper().startswith("ASRL")]
            empty_text = "Нет COM-портов"

        filtered = [r for r in filtered if r not in self._busy_ports]

        for res in filtered:
            self.port_combo.addItem(res, res)
        if not filtered:
            self.port_combo.addItem(empty_text, None)
        self.log.emit("Порты обновлены")

    def _on_connect_clicked(self):
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "Ошибка", "выберите порт")
            return

        iface = self.cmb_iface.currentData()
        baud = self.baud_combo.currentData() if iface == "ASRL" else 0

        if iface == "ASRL" and port.upper().startswith("COM"):
            port = f"ASRL{port[3:]}::INSTR"

        self.log.emit(f"Подключение к {port}...")
        self.connect_requested.emit(
            port, "RS232" if iface == "ASRL" else "USB", baud)