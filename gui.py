import pyvisa
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QDoubleSpinBox, QPushButton, QComboBox, QPlainTextEdit, QMessageBox, QFormLayout
from serial_worker import SerialWorker
from styles import *

class ChannelPanel(QGroupBox):
    set_v_requested = pyqtSignal(int, float)
    set_i_requested = pyqtSignal(int, float)

    def __init__(self, ch: int, v_min=3.3, v_max=5.0, i_min=0.0, i_max=0.05, accent_key: str = "green"):
        super().__init__(f"CH{ch}")
        self.ch = ch
        self._accent_key = accent_key

        layout = QFormLayout()
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(10)

        self.v_spin = QDoubleSpinBox()
        self.v_spin.setRange(v_min, v_max)
        self.v_spin.setDecimals(2)
        self.v_spin.setStepType(QDoubleSpinBox.StepType.DefaultStepType)
        self.v_spin.setSingleStep(0.01)
        self.v_spin.setSuffix(" В")
        self.v_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)

        self.i_spin = QDoubleSpinBox()
        self.i_spin.setRange(i_min, i_max)
        self.i_spin.setDecimals(3)
        self.i_spin.setStepType(QDoubleSpinBox.StepType.DefaultStepType)
        self.i_spin.setSingleStep(0.001)
        self.i_spin.setSuffix(" А")

        btn_v = QPushButton("Установить")
        btn_i = QPushButton("Установить")
        btn_v.clicked.connect(lambda: self.set_v_requested.emit(self.ch, self.v_spin.value()))
        btn_i.clicked.connect(lambda: self.set_i_requested.emit(self.ch, self.i_spin.value()))

        row_v = QHBoxLayout(); row_v.addWidget(self.v_spin, 1); row_v.addWidget(btn_v)
        row_v.setSpacing(8)
        row_i = QHBoxLayout(); row_i.addWidget(self.i_spin, 1); row_i.addWidget(btn_i)
        row_i.setSpacing(8)

        lbl_v = QLabel(
            f'Напряжение:<br>'
            f'<span style="color:#808080">{v_min}-{v_max} В</span>'
        )
        lbl_v.setTextFormat(Qt.TextFormat.RichText)
        lbl_v.setWordWrap(True)

        lbl_i = QLabel(
            f'Ток:<br>'
            f'<span style="color:#808080">{i_min}-{i_max} А</span>'
        )
        lbl_i.setTextFormat(Qt.TextFormat.RichText)
        lbl_i.setWordWrap(True)

        layout.addRow(lbl_v, row_v)
        layout.addRow(lbl_i, row_i)

        self.setLayout(layout)

        border = CHANNEL_COLORS[accent_key]
        self.setStyleSheet(CHANNEL_STYLE_TEMPLATE.format(border=border))

class MainWindow(QMainWindow):
    sig_open = pyqtSignal(str, int)
    sig_close = pyqtSignal()
    sig_set_v = pyqtSignal(int, float)
    sig_set_i = pyqtSignal(int, float)
    sig_set_out = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("UDP3305C")
        self.resize(640, 600)

        self._connected = False
        self.rm = None
        try:
            self.rm = pyvisa.ResourceManager('@ivi')
        except Exception:
            try:
                self.rm = pyvisa.ResourceManager('@py')
            except Exception as e:
                print(f"VISA не инициализирован: {e}")

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        conn_box = QGroupBox("Подключение")
        conn_layout = QFormLayout()
        conn_layout.setVerticalSpacing(8)
        conn_layout.setHorizontalSpacing(10)
        self.conn_layout = conn_layout

        self.cmb_iface = QComboBox()
        self.cmb_iface.addItem("USB", "USB")
        self.cmb_iface.addItem("RS232", "ASRL")
        self.cmb_iface.currentIndexChanged.connect(self.on_iface_changed)
        conn_layout.addRow("Интерфейс:", self.cmb_iface)
        conn_layout.setSpacing(8)

        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        btn_refresh = QPushButton("Обновить")
        btn_refresh.clicked.connect(self.refresh_ports)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(btn_refresh)
        conn_layout.addRow("Порт:", port_row)

        baud_row = QHBoxLayout()
        self.baud_combo = QComboBox()
        for b in (9600, 19200, 38400, 57600, 115200):
            self.baud_combo.addItem(str(b), b)
        self.baud_combo.setCurrentText("9600")
        baud_row.addWidget(self.baud_combo, 1)
        conn_layout.addRow("Бод:", baud_row)
        self.baud_row = baud_row

        connect_row = QHBoxLayout()
        self.btn_connect = QPushButton("Подключить")
        self.btn_connect.setCheckable(True)
        self.btn_connect.toggled.connect(self.on_connect_toggled)
        connect_row.addWidget(self.btn_connect)
        conn_layout.addRow(connect_row)

        status_row = QHBoxLayout()
        self.lbl_status = QLabel("Отключено")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setMinimumHeight(28)
        status_row.addWidget(self.lbl_status, 1)
        conn_layout.addRow(status_row)

        conn_box.setLayout(conn_layout)
        root.addWidget(conn_box)

        ch_layout = QHBoxLayout()
        self.ch1 = ChannelPanel(1, accent_key="green")
        self.ch2 = ChannelPanel(2, accent_key="blue")
        ch_layout.addWidget(self.ch1)
        ch_layout.addWidget(self.ch2)
        root.addLayout(ch_layout)

        out_box = QGroupBox("Выход")
        out_layout = QHBoxLayout()
        self.btn_output = QPushButton("Включить выход")
        self.btn_output.setCheckable(True)
        self.btn_output.toggled.connect(self.on_output_toggled)
        out_layout.addWidget(self.btn_output)
        out_box.setLayout(out_layout)
        root.addWidget(out_box)

        log_box = QGroupBox("Лог")
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(8, 8, 8, 8)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        log_layout.addWidget(self.log)
        root.addWidget(log_box, 1)

        self.thread = QThread()
        self.worker = SerialWorker()
        self.worker.moveToThread(self.thread)

        self.sig_open.connect(self.worker.open_port)
        self.sig_close.connect(self.worker.close_port)
        self.sig_set_v.connect(self.worker.set_voltage)
        self.sig_set_i.connect(self.worker.set_current)
        self.sig_set_out.connect(self.worker.set_output)

        self.worker.error_occurred.connect(self.on_error)
        self.worker.connected.connect(self.on_connected)

        self.ch1.set_v_requested.connect(self.on_set_v)
        self.ch1.set_i_requested.connect(self.on_set_i)
        self.ch2.set_v_requested.connect(self.on_set_v)
        self.ch2.set_i_requested.connect(self.on_set_i)

        self.thread.start()

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(700)

        self._set_status("disconnected")

        self.shortcut_q = QShortcut(QKeySequence("q"), self)
        self.shortcut_q.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_q.activated.connect(self.close)

        self.shortcut_ctrl_c = QShortcut(QKeySequence("Ctrl+C"), self)
        self.shortcut_ctrl_c.activated.connect(self.close)

        self.on_iface_changed()

    def _set_status(self, state: str, text: str | None = None):
        cfg = STATUS_COLORS[state]
        self.lbl_status.setText(text if text is not None else cfg["text"])
        self.lbl_status.setStyleSheet(
            STATUS_STYLE_TEMPLATE.format(
                color=cfg["color"], bg=cfg["bg"], border=cfg["border"]
            )
        )

    def on_connect_toggled(self, checked: bool):
        if checked:
            port = self.port_combo.currentData()
            if not port:
                QMessageBox.warning(self, "Ошибка", "выберите порт")
                self.btn_connect.setChecked(False)
                return

            iface = self.cmb_iface.currentData()
            baud = self.baud_combo.currentData() if iface == "ASRL" else 0

            if iface == "ASRL" and port.upper().startswith("COM"):
                try:
                    num = port[3:]
                    port = f"ASRL{num}::INSTR"
                except Exception:
                    pass

            self.append_log(f"Подключение к {port}...")
            self.sig_open.emit(port, baud)
        else:
            self.sig_close.emit()
            self.poll_timer.stop()

    def on_connected(self, ok: bool, port: str):
        if ok:
            self._connected = True
            self._set_status("connected")
            self.btn_connect.setText("Отключить")
            self.poll_timer.start()
            self.append_log(f"Подключено к {port}")
        else:
            was_connected = self._connected
            self._connected = False
            self._set_status("disconnected")
            self.btn_connect.blockSignals(True)
            self.btn_connect.setChecked(False)
            self.btn_connect.blockSignals(False)
            self.btn_connect.setText("Подключить")
            self.poll_timer.stop()

            if was_connected:
                self.append_log(f"Отключено от {port}")
            else:
                self.append_log(f"Не удалось подключиться к {port}")

    def on_set_v(self, ch: int, value: float):
        if not self._connected:
            self.on_error(f"не удалось установить напряжение CH{ch}, нет подключения")
            return
        self.sig_set_v.emit(ch, value)
        self.append_log(f"CH{ch}: установлено напряжение {value:.2f} В")

    def on_set_i(self, ch: int, value: float):
        if not self._connected:
            self.on_error(f"не удалось установить ток CH{ch}, нет подключения")
            return
        self.sig_set_i.emit(ch, value)
        self.append_log(f"CH{ch}: установлен ток {value:.2f} А")

    def on_output_toggled(self, checked: bool):
        if not self._connected:
            self.btn_output.blockSignals(True)
            self.btn_output.setChecked(False)
            self.btn_output.blockSignals(False)
            self.btn_output.setText("Включить выход")
            self.on_error("не удалось включить выход, нет подключения")
            return
        self.sig_set_out.emit(checked)
        self.btn_output.setText("Выключить выход" if checked else "Включить выход")
        self.append_log(f"Выход {'включен' if checked else 'выключен'}")

    def on_error(self, msg: str):
        if "нет подключения" in msg:
            self._connected = False
            self._set_status("disconnected")
            self.btn_output.blockSignals(True)
            self.btn_output.setChecked(False)
            self.btn_output.blockSignals(False)
            self.btn_output.setText("Включить выход")
            self.btn_connect.blockSignals(True)
            self.btn_connect.setChecked(False)
            self.btn_connect.blockSignals(False)
            self.btn_connect.setText("Подключить")
            self.poll_timer.stop()
        self.append_log("Ошибка: " + msg)

    def append_log(self, msg: str):
        self.log.appendPlainText(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event):
        self.poll_timer.stop()
        self.sig_close.emit()
        self.thread.quit()
        self.thread.wait(1000)
        super().closeEvent(event)

    def on_iface_changed(self):
        is_serial = self.cmb_iface.currentData() == "ASRL"
        self.conn_layout.setRowVisible(self.baud_row, is_serial)
        self.refresh_ports()
    
    def refresh_ports(self):
        iface = self.cmb_iface.currentData() if hasattr(self, "cmb_iface") else "USB"

        self.append_log("Обновление портов...")

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

        for res in filtered:
            self.port_combo.addItem(res, res)

        if not filtered:
            self.port_combo.addItem(empty_text, None)
        
        self.append_log("Порты обновлены")