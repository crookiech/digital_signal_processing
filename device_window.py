import pyvisa
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QPlainTextEdit, QLabel, QComboBox, QFormLayout, QMessageBox)
from device_model import DeviceState
from channels import ChannelPanel, ChannelPanel3
from styles import STATUS_COLORS, STATUS_STYLE_TEMPLATE, OPERATING_MODES

class DeviceWindow(QWidget):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        st = session.state

        self.setWindowTitle("UDP3305C")
        self.resize(640, 600)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self.rm = None
        try:
            self.rm = pyvisa.ResourceManager('@ivi')
        except Exception:
            try:
                self.rm = pyvisa.ResourceManager('@py')
            except Exception as e:
                print(f"VISA не инициализирован: {e}")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        conn_box = QGroupBox("Подключение")
        conn_layout = QFormLayout()
        conn_layout.setVerticalSpacing(8)
        conn_layout.setHorizontalSpacing(10)
        conn_layout.setSpacing(8)
        self.conn_layout = conn_layout

        self.cmb_iface = QComboBox()
        self.cmb_iface.addItem("USB", "USB")
        self.cmb_iface.addItem("RS232", "ASRL")
        conn_layout.addRow("Интерфейс:", self.cmb_iface)

        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        btn_refresh = QPushButton("Обновить")
        btn_refresh.clicked.connect(self.refresh_ports)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(btn_refresh)
        conn_layout.addRow("Порт:", port_row)

        self.baud_row = QHBoxLayout()
        self.baud_combo = QComboBox()
        for b in (9600, 19200, 38400, 57600, 115200):
            self.baud_combo.addItem(str(b), b)
        self.baud_combo.setCurrentText(str(st.baud or 9600))
        self.baud_row.addWidget(self.baud_combo, 1)
        conn_layout.addRow("Бод:", self.baud_row)

        connect_row = QHBoxLayout()
        self.btn_connect = QPushButton("Подключить")
        self.btn_connect.setCheckable(True)
        self.btn_connect.toggled.connect(self._on_connect_toggled)
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
        self.ch3 = ChannelPanel3(3, accent_key="orange")
        root.addWidget(self.ch3)
        self.channels = {1: self.ch1, 2: self.ch2, 3: self.ch3}

        out_box = QGroupBox("Выход")
        out_layout = QHBoxLayout()
        self.btn_output = QPushButton("Включить выход")
        self.btn_output.setCheckable(True)
        self.btn_output.toggled.connect(self._on_output)
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

        for ch in (self.ch1, self.ch2, self.ch3):
            ch.set_v_requested.connect(self._on_set_v)
            ch.set_i_requested.connect(self._on_set_i)
        self.ch1.mode_changed.connect(self._on_mode_changed)
        self.ch2.mode_changed.connect(self._on_mode_changed)

        is_serial = st.interface.upper() in ("RS232", "ASRL", "COM")
        self.cmb_iface.setCurrentIndex(1 if is_serial else 0)
        self.cmb_iface.currentIndexChanged.connect(self.on_iface_changed)
        self.on_iface_changed()
        if st.port:
            i = self.port_combo.findData(st.port)
            if i >= 0:
                self.port_combo.setCurrentIndex(i)

        self.apply_state(st)

    def on_iface_changed(self):
        is_serial = self.cmb_iface.currentData() == "ASRL"
        self.conn_layout.setRowVisible(self.baud_row, is_serial)
        self.refresh_ports()

    def refresh_ports(self):
        iface = self.cmb_iface.currentData()
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

    def _on_connect_toggled(self, checked: bool):
        if checked:
            port = self.port_combo.currentData()
            if not port:
                QMessageBox.warning(self, "Ошибка", "выберите порт")
                self.btn_connect.blockSignals(True)
                self.btn_connect.setChecked(False)
                self.btn_connect.blockSignals(False)
                return

            iface = self.cmb_iface.currentData()
            baud = self.baud_combo.currentData() if iface == "ASRL" else 0
            if iface == "ASRL" and port.upper().startswith("COM"):
                port = f"ASRL{port[3:]}::INSTR"

            st = self.session.state
            st.port = port
            st.interface = "RS232" if iface == "ASRL" else "USB"
            st.baud = baud

            self.append_log(f"Подключение к {port}...")
            self.session.open()
        else:
            self.session.close()

    def _on_set_v(self, ch: int, val: float):
        if not self.session.state.connected:
            self.append_log(f"Ошибка: не удалось установить напряжение CH{ch}, нет подключения")
            return
        self.session.set_voltage(ch, val)
        self.append_log(f"CH{ch}: установлено напряжение {val:.2f} В")

    def _on_set_i(self, ch: int, val: float):
        if not self.session.state.connected:
            self.append_log(f"Ошибка: не удалось установить ток CH{ch}, нет подключения")
            return
        self.session.set_current(ch, val)
        self.append_log(f"CH{ch}: установлен ток {val:.2f} А")

    def _on_mode_changed(self, ch: int, key: str):
        cfg = OPERATING_MODES.get(key)
        if cfg is None:
            return
        self.append_log(
            f"CH{ch}: режим {cfg['label']} "
            f"({cfg['v_min']}-{cfg['v_max']} В, "
            f"{cfg['i_min']}-{cfg['i_max']} А)")
        if self.session.state.connected:
            self.session.request_voltage(ch)
            self.session.request_current(ch)

    def _on_output(self, on: bool):
        if not self.session.state.connected:
            self.btn_output.blockSignals(True)
            self.btn_output.setChecked(False)
            self.btn_output.blockSignals(False)
            self.btn_output.setText("Включить выход")
            self.append_log("Ошибка: не удалось включить выход, нет подключения")
            return
        self.session.set_output(on)
        self.session.state.output_on = on
        self.btn_output.setText("Выключить выход" if on else "Включить выход")
        self.append_log(f"Выход {'включен' if on else 'выключен'}")

    def apply_state(self, st: DeviceState):
        self._set_status(st.connected)

        self.btn_connect.blockSignals(True)
        self.btn_connect.setChecked(st.connected)
        self.btn_connect.blockSignals(False)
        self.btn_connect.setText("Отключить" if st.connected else "Подключить")

        for ch in (1, 2):
            cs = st.channels.get(ch)
            if cs is not None:
                self.channels[ch].v_spin.setValue(cs.voltage)
                self.channels[ch].i_spin.setValue(cs.current)

        cs3 = st.channels.get(3)
        if cs3 is not None:
            self.ch3.set_voltage_display(cs3.voltage)
            self.ch3.i_spin.setValue(cs3.current)

        self.btn_output.blockSignals(True)
        self.btn_output.setChecked(st.output_on)
        self.btn_output.blockSignals(False)
        self.btn_output.setText("Выключить выход" if st.output_on else "Включить выход")

    def _set_status(self, connected: bool):
        cfg = STATUS_COLORS["connected" if connected else "disconnected"]
        self.lbl_status.setText(cfg["text"])
        self.lbl_status.setStyleSheet(
            STATUS_STYLE_TEMPLATE.format(
                color=cfg["color"], bg=cfg["bg"], border=cfg["border"]))

    def append_log(self, msg: str):
        self.log.appendPlainText(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())
