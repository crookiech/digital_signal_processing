import time
import sys
from ipaddress import IPv4Address, IPv4Network
from datetime import datetime
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QLineEdit, QComboBox, 
                             QTableWidget, QTableWidgetItem, QMessageBox, 
                             QGroupBox, QRadioButton, QFormLayout, QHeaderView, 
                             QCheckBox, QFileDialog, QGridLayout, QScrollArea)
from PyQt6.QtCore import Qt, QSettings, QTimer
from dhcp_server import MiniDhcpServer


import pyvisa
from instrument_worker import MeasurementWorker
from dialogs import OptionsDialog, FunctionDialog, MathDialog
from network_utils import LanConfigurator, list_adapters
from lan_workers import OperationWorker, open_instrument, prepare_lan

class MultimeterApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UT8805E")
        self.resize(1100, 750)
        self.instrument = None
        self.worker = None
        self.rm = None
        self.is_connected = False
        self.dhcp_server = None # Ссылка на запущенный DHCP-сервер
        self.dhcp_timer = QTimer(self)
        self.dhcp_timer.setInterval(500)
        self.dhcp_timer.timeout.connect(self.check_dhcp_status)
        self._dhcp_status = ""
        self.lan_configurator = LanConfigurator()
        self.lan_plan = None
        self.operation = None
        self._close_after_restore = False
        self._last_dhcp_message = ""
        
        self.measure_interval = 100 
        self.max_points = 10000     
        self.is_infinite = True
        self.skip_repeats = False
        self.current_func = "VOLT:DC" 
        
        self.settings = QSettings("MyLab", "UT8805E_App")

        self.init_ui()
        self.check_visa_backends()
        self.load_settings()
        self.btn_restore_lan.setEnabled(self.lan_configurator.has_backup())
        QTimer.singleShot(0, self.refresh_adapters)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        left_panel = QVBoxLayout()

        conn_group = QGroupBox("Подключение")
        conn_layout = QVBoxLayout()

        iface_layout = QHBoxLayout()
        self.radio_usb = QRadioButton("USB")
        self.radio_lan = QRadioButton("LAN")
        self.radio_rs232 = QRadioButton("RS232")
        self.radio_usb.setChecked(True)
        iface_layout.addWidget(self.radio_usb)
        iface_layout.addWidget(self.radio_lan)
        iface_layout.addWidget(self.radio_rs232)
        conn_layout.addLayout(iface_layout)

        self.lan_group = QGroupBox("LAN Настройки")
        lan_form = QFormLayout()
        self.adapter_combo = QComboBox()
        self.adapter_combo.setMinimumContentsLength(18)
        self.adapter_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.btn_refresh_adapters = QPushButton("Обновить адаптеры")
        self.btn_refresh_adapters.clicked.connect(self.refresh_adapters)
        self.pc_ip_edit = QLineEdit()
        self.pc_ip_edit.setReadOnly(True)
        self.pc_ip_edit.setPlaceholderText("Будет определён при настройке LAN")
        self.ip_edit = QLineEdit()
        self.ip_edit.setPlaceholderText("Адрес с экрана прибора или из DHCP")
        self.mask_edit = QLineEdit()
        self.mask_edit.setReadOnly(True)
        self.gateway_edit = QLineEdit()
        self.gateway_edit.setReadOnly(True)
        self.lease_combo = QComboBox()
        self.lease_combo.setMinimumContentsLength(18)
        self.lease_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.lease_combo.currentIndexChanged.connect(self.select_lease)
        self.lan_state = QLabel("Выберите Ethernet и нажмите «Настроить LAN».")
        self.lan_state.setWordWrap(True)
        self.lan_state.setMinimumHeight(96)
        self.btn_start_dhcp = QPushButton("Настроить LAN")
        self.btn_start_dhcp.clicked.connect(self.toggle_dhcp_server)

        self.btn_update_ip = QPushButton("Обновить IP из DHCP")
        self.btn_update_ip.clicked.connect(self.update_ip_from_dhcp)
        self.btn_restore_lan = QPushButton("Восстановить Ethernet")
        self.btn_restore_lan.clicked.connect(self.restore_lan)
        
        lan_form.addRow("Ethernet:", self.adapter_combo)
        lan_form.addRow("", self.btn_refresh_adapters)
        lan_form.addRow("IP ПК:", self.pc_ip_edit)
        lan_form.addRow("Маска:", self.mask_edit)
        lan_form.addRow("Шлюз:", self.gateway_edit)
        lan_form.addRow("", self.btn_start_dhcp)
        lan_form.addRow("Выданные адреса:", self.lease_combo)
        lan_form.addRow("IP мультиметра:", self.ip_edit)
        lan_form.addRow("", self.btn_update_ip)
        lan_form.addRow("", self.btn_restore_lan)
        lan_form.addRow(self.lan_state)
        self.lan_group.setLayout(lan_form)


        self.lan_group.setVisible(False)
        conn_layout.addWidget(self.lan_group)

        self.serial_group = QGroupBox()
        serial_form = QFormLayout()
        self.combo_com = QComboBox()
        self.btn_refresh_com = QPushButton("Обновить")
        self.btn_refresh_com.clicked.connect(self.refresh_com_ports)
        serial_form.addRow("COM-порт:", self.combo_com)
        serial_form.addRow("", self.btn_refresh_com)
        self.serial_group.setLayout(serial_form)
        self.serial_group.setVisible(False)
        conn_layout.addWidget(self.serial_group)

        self.usb_label = QLabel("USB: будет найден автоматически")
        conn_layout.addWidget(self.usb_label)

        self.btn_connect = QPushButton("Подключиться")
        self.btn_connect.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.btn_connect)
        conn_group.setLayout(conn_layout)
        left_panel.addWidget(conn_group)

        toolbar_group = QGroupBox("Функции")
        toolbar_layout = QGridLayout()
        self.btn_func = QPushButton("Функция")
        self.btn_func.clicked.connect(self.open_function_dialog)
        self.btn_math = QPushButton("Математика")
        self.btn_math.clicked.connect(self.open_math_dialog)
        self.btn_options = QPushButton("Настройки")
        self.btn_options.clicked.connect(self.open_options_dialog)
        toolbar_layout.addWidget(self.btn_func, 0, 0)
        toolbar_layout.addWidget(self.btn_math, 0, 1)
        toolbar_layout.addWidget(self.btn_options, 1, 0, 1, 2)
        toolbar_group.setLayout(toolbar_layout)
        left_panel.addWidget(toolbar_group)

        ctrl_group = QGroupBox("Быстрое управление")
        ctrl_layout = QFormLayout()
        self.range_combo = QComboBox()
        self.range_combo.addItems(["AUTO", "200mV", "2V", "20V", "200V", "1000V"])
        self.range_combo.currentTextChanged.connect(self.change_range)
        ctrl_layout.addRow("Диапазон:", self.range_combo)

        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["FAST", "MED", "SLOW"])
        self.speed_combo.currentTextChanged.connect(self.change_speed)
        ctrl_layout.addRow("Скорость:", self.speed_combo)

        self.imp_check = QCheckBox("Импеданс 10 ГОм")
        self.imp_check.setChecked(True) 
        self.imp_check.stateChanged.connect(self.change_impedance)
        ctrl_layout.addRow("", self.imp_check)
        ctrl_group.setLayout(ctrl_layout)
        left_panel.addWidget(ctrl_group)

        self.btn_start = QPushButton("Старт опроса")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start_measurement)
        self.btn_stop = QPushButton("Стоп")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_measurement)
        left_panel.addWidget(self.btn_start)
        left_panel.addWidget(self.btn_stop)
        left_panel.addStretch()
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(390)
        left_scroll.setWidget(left_widget)
        main_layout.addWidget(left_scroll, 1)

        right_panel = QVBoxLayout()
        display_group = QGroupBox("Показания")
        display_layout = QVBoxLayout()
        self.value_label = QLabel("---.---")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setStyleSheet("font-size: 48px; font-weight: bold; color: #00FF00; background-color: black;")
        self.unit_label = QLabel("VDC")
        self.unit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.unit_label.setStyleSheet("font-size: 24px; color: white; background-color: black;")
        display_layout.addWidget(self.value_label)
        display_layout.addWidget(self.unit_label)
        display_group.setLayout(display_layout)
        right_panel.addWidget(display_group)

        log_group = QGroupBox("Лог измерений")
        log_layout = QVBoxLayout()
        log_buttons = QHBoxLayout()
        self.btn_clear_log = QPushButton("Очистить")
        self.btn_clear_log.clicked.connect(self.clear_log)
        self.btn_save_log = QPushButton("Сохранить")
        self.btn_save_log.clicked.connect(self.save_log)
        log_buttons.addWidget(self.btn_clear_log)
        log_buttons.addWidget(self.btn_save_log)
        log_layout.addLayout(log_buttons)
        
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["№", "Время", "Значение"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        log_layout.addWidget(self.table)
        log_group.setLayout(log_layout)
        right_panel.addWidget(log_group)
        main_layout.addLayout(right_panel, 2)

        self.radio_usb.toggled.connect(self.update_interface_fields)
        self.radio_lan.toggled.connect(self.update_interface_fields)
        self.radio_rs232.toggled.connect(self.update_interface_fields)

    def load_settings(self):
        self.ip_edit.setText(self.settings.value("lan/ip", ""))
        
        iface = self.settings.value("conn/interface", "USB")
        if iface == "LAN": self.radio_lan.setChecked(True)
        elif iface == "RS232": self.radio_rs232.setChecked(True)
        else: self.radio_usb.setChecked(True)

    def save_settings(self):
        self.settings.setValue("lan/ip", self.ip_edit.text())
        self.settings.setValue("lan/adapter", self.adapter_combo.currentData())
        
        if self.radio_lan.isChecked(): self.settings.setValue("conn/interface", "LAN")
        elif self.radio_rs232.isChecked(): self.settings.setValue("conn/interface", "RS232")
        else: self.settings.setValue("conn/interface", "USB")

    def refresh_com_ports(self):
        self.combo_com.clear()
        try:
            resources = self.rm.list_resources('ASRL?*::INSTR')
            for r in resources:
                self.combo_com.addItem(r)
        except Exception:
            self.combo_com.addItem("ASRL3::INSTR")

    def update_interface_fields(self):
        self.lan_group.setVisible(self.radio_lan.isChecked())
        self.serial_group.setVisible(self.radio_rs232.isChecked())
        self.usb_label.setVisible(self.radio_usb.isChecked())
        if self.radio_rs232.isChecked() and self.combo_com.count() == 0:
            self.refresh_com_ports()

    def set_lan_message(self, message):
        self.lan_state.setText(message)
        self.statusBar().showMessage(message)

    def update_controls(self):
        busy = self.operation is not None
        prepared = self.lan_plan is not None
        self.adapter_combo.setEnabled(not busy and not prepared)
        self.btn_refresh_adapters.setEnabled(not busy and not prepared)
        self.btn_start_dhcp.setEnabled(not busy and not self.is_connected)
        self.btn_restore_lan.setEnabled(
            not busy and (prepared or self.lan_configurator.has_backup()))
        self.btn_update_ip.setEnabled(not busy and self.dhcp_server is not None)
        self.lease_combo.setEnabled(not busy and not self.is_connected)
        self.ip_edit.setEnabled(not busy and not self.is_connected)
        self.btn_connect.setEnabled(not busy)
        for radio in (self.radio_usb, self.radio_lan, self.radio_rs232):
            radio.setEnabled(not busy and not self.is_connected and not prepared)
        self.btn_start.setEnabled(not busy and self.is_connected and self.worker is None)

    def run_operation(self, operation, on_success, on_error=None):
        if self.operation is not None:
            return
        worker = OperationWorker(operation, self)
        self.operation = worker
        worker.succeeded.connect(on_success)
        worker.failed.connect(on_error or self.operation_failed)
        worker.finished.connect(self.operation_finished)
        self.update_controls()
        worker.start()

    def operation_finished(self):
        worker = self.operation
        self.operation = None
        if worker:
            worker.deleteLater()
        self.update_controls()
        if self._close_after_restore and not self.lan_configurator.has_backup():
            self._close_after_restore = False
            self.close()

    def operation_failed(self, message):
        self._close_after_restore = False
        self.set_lan_message(message)
        QMessageBox.warning(self, "Ошибка LAN", message)

    def refresh_adapters(self):
        if self.operation is not None or self.lan_plan is not None:
            return
        self.set_lan_message("Поиск Ethernet-адаптеров…")
        self.run_operation(list_adapters, self.adapters_loaded)

    def adapters_loaded(self, adapters):
        previous = self.adapter_combo.currentData() or self.settings.value("lan/adapter", "")
        self.adapter_combo.clear()
        ethernet = [item for item in adapters if item["ethernet"] and item["guid"]]
        for adapter in ethernet:
            ips = ", ".join(a["ip"] for a in adapter["addresses"]) or "нет IPv4"
            state = "кабель подключён" if adapter["connected"] else "нет кабеля"
            self.adapter_combo.addItem(f"{adapter['name']} — {ips}, {state}", adapter["guid"])
            self.adapter_combo.setItemData(
                self.adapter_combo.count() - 1,
                f"{adapter.get('description', adapter['name'])}\n{ips}\n{state}",
                Qt.ItemDataRole.ToolTipRole)
        active = [a for a in ethernet if a["connected"]]
        remembered = self.adapter_combo.findData(previous)
        if remembered >= 0:
            self.adapter_combo.setCurrentIndex(remembered)
        elif len(active) == 1:
            self.adapter_combo.setCurrentIndex(self.adapter_combo.findData(active[0]["guid"]))
        else:
            self.adapter_combo.setCurrentIndex(-1)
        if self.lan_configurator.has_backup():
            self.set_lan_message("Есть сохранённые настройки Ethernet. Нажмите «Восстановить Ethernet» перед новой настройкой.")
        elif ethernet:
            self.set_lan_message("Выберите Ethernet с кабелем мультиметра и нажмите «Настроить LAN».")
        else:
            self.set_lan_message("Физический Ethernet-адаптер не найден.")

    def toggle_dhcp_server(self):
        if self.dhcp_server is not None:
            self.stop_dhcp()
            self.set_lan_message("DHCP остановлен. Настройки IP ПК сохраняются до восстановления Ethernet.")
            return
        if self.lan_plan is not None:
            self.start_dhcp(self.lan_plan)
            return
        guid = self.adapter_combo.currentData()
        if not guid:
            QMessageBox.information(self, "Ethernet", "Выберите Ethernet-адаптер с кабелем мультиметра.")
            return
        self.set_lan_message("Подготовка IPv4 выбранного Ethernet…")
        self.run_operation(lambda: prepare_lan(self.lan_configurator, guid), self.start_dhcp)

    def start_dhcp(self, plan):
        self.lan_plan = plan
        index = self.adapter_combo.findData(plan["adapter"]["guid"])
        if index >= 0:
            self.adapter_combo.setItemText(
                index, f"{plan['adapter']['name']} — {plan['server_ip']}, кабель подключён")
        self.pc_ip_edit.setText(plan["server_ip"])
        self.mask_edit.setText(plan["mask"])
        self.gateway_edit.setText(plan["gateway"])
        self.ip_edit.clear()
        self.lease_combo.clear()
        self._last_dhcp_message = ""
        self._dhcp_status = (
            f"DHCP на {plan['adapter']['name']}, IP ПК: {plan['server_ip']} "
            f"(пул: {plan['pool_start']}–{plan['pool_end']})"
        )
        try:
            self.dhcp_server = MiniDhcpServer(
                interface=plan["capture_interface"], pool_start=plan["pool_start"],
                pool_end=plan["pool_end"], subnet_mask=plan["mask"],
                gateway=plan["gateway"], server_ip=plan["server_ip"],
            )
            self.dhcp_server.start()
            self.btn_start_dhcp.setText("Остановить DHCP")
            self.set_lan_message(self._dhcp_status + ". Запуск…")
            self.dhcp_timer.start()
        except Exception as exc:
            self.dhcp_server = None
            # Defer until the preparation worker has fully finished.
            QTimer.singleShot(0, lambda message=str(exc): self.dhcp_failed(message))
        self.update_controls()

    def stop_dhcp(self):
        self.dhcp_timer.stop()
        if self.dhcp_server:
            self.dhcp_server.stop()
            self.dhcp_server = None
        self.btn_start_dhcp.setText("Запустить DHCP" if self.lan_plan else "Настроить LAN")
        self.update_controls()

    def dhcp_failed(self, message):
        if self.operation is not None:
            QTimer.singleShot(100, lambda: self.dhcp_failed(message))
            return
        self.disconnect_instrument()
        self.stop_dhcp()
        self.set_lan_message(f"Ошибка DHCP: {message}. Восстановление Ethernet…")
        def restored(_):
            self.lan_restored(None)
            self.operation_failed(f"DHCP не запущен: {message}. Исходные настройки Ethernet восстановлены.")
        self.run_operation(self.lan_configurator.restore, restored)

    def check_dhcp_status(self):
        server = self.dhcp_server
        if server is None:
            return
        if server.error or not server.is_alive():
            self.dhcp_failed(server.error or "Поток DHCP-сервера завершился.")
            return
        if not server.running:
            return
        leases = server.get_leases()
        entries = [(mac, ip) for mac, ip in leases.items()]
        previous = self.lease_combo.currentData()
        existing = [self.lease_combo.itemData(i) for i in range(self.lease_combo.count())]
        if entries != existing:
            self.lease_combo.blockSignals(True)
            self.lease_combo.clear()
            for mac, ip in entries:
                self.lease_combo.addItem(f"{ip} — {mac}", (mac, ip))
            if previous in entries:
                self.lease_combo.setCurrentIndex(entries.index(previous))
            elif len(entries) != 1:
                self.lease_combo.setCurrentIndex(-1)
            self.lease_combo.blockSignals(False)
            if not self.is_connected:
                self.select_lease()
        suffix = (
            "Адрес выдан. Нажмите «Подключиться» для проверки прибора."
            if leases else "Ожидание запроса. На мультиметре включите DHCP и нажмите Apply."
        )
        message = f"{self._dhcp_status}. {suffix}"
        if not self.is_connected and self.operation is None and message != self._last_dhcp_message:
            self.set_lan_message(message)
            self._last_dhcp_message = message

    def select_lease(self, index=None):
        if not self.is_connected:
            selected = self.lease_combo.currentData()
            if selected:
                self.ip_edit.setText(selected[1])

    def update_ip_from_dhcp(self):
        self.check_dhcp_status()
        selected = self.lease_combo.currentData()
        if selected:
            self.select_lease()
        else:
            QMessageBox.information(
                self, "DHCP", "Адрес ещё не выдан либо нужно выбрать клиента в списке. "
                "Включите DHCP на мультиметре и примените настройку кнопкой Apply.")

    def restore_lan(self):
        if self.operation is not None:
            return
        self.disconnect_instrument()
        self.stop_dhcp()
        self.set_lan_message("Восстановление исходных настроек Ethernet…")
        self.run_operation(self.lan_configurator.restore, self.lan_restored)

    def lan_restored(self, result):
        if self.lan_plan:
            adapter = self.lan_plan["adapter"]
            index = self.adapter_combo.findData(adapter["guid"])
            if index >= 0:
                self.adapter_combo.setItemText(index, f"{adapter['name']} — настройки восстановлены")
        self.lan_plan = None
        self.pc_ip_edit.clear()
        self.mask_edit.clear()
        self.gateway_edit.clear()
        self.ip_edit.clear()
        self.lease_combo.clear()
        self.btn_start_dhcp.setText("Настроить LAN")
        self.set_lan_message("Исходные настройки Ethernet восстановлены.")

    def check_visa_backends(self):
        try:
            self.rm = pyvisa.ResourceManager('@ivi')
            self.statusBar().showMessage("NI-VISA найден.")
        except Exception:
            # Пытаемся использовать pyvisa-py
            try:
                self.rm = pyvisa.ResourceManager('@py')
                self.statusBar().showMessage("Используется pyvisa-py.")
            except Exception as e:
                # Предлагаем скачать NI-VISA
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Icon.Critical)
                msg.setWindowTitle("Ошибка VISA")
                msg.setText("Не удалось загрузить бэкенд VISA.\n\n"
                            "Для работы с USB/LAN необходим драйвер NI-VISA.")
                download_btn = msg.addButton("Скачать NI-VISA", QMessageBox.ButtonRole.ActionRole)
                msg.addButton("Выход", QMessageBox.ButtonRole.RejectRole)
                msg.exec()
                
                if msg.clickedButton() == download_btn:
                    import webbrowser
                    webbrowser.open("https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html")
                sys.exit(1)

    def get_resource_name(self):
        if self.radio_usb.isChecked():
            try:
                for r in self.rm.list_resources():
                    if 'USB' in r and 'INSTR' in r: return r
            except: pass
            return None
        elif self.radio_lan.isChecked():
            return f"TCPIP0::{self.ip_edit.text().strip()}::INSTR"
        elif self.radio_rs232.isChecked():
            return self.combo_com.currentText()
        return None

    def toggle_connection(self):
        if self.is_connected:
            self.disconnect_instrument()
            return
        try:
            if self.radio_lan.isChecked():
                ip = IPv4Address(self.ip_edit.text().strip())
                if self.lan_plan:
                    network = IPv4Network(f"{self.lan_plan['server_ip']}/{self.lan_plan['mask']}", strict=False)
                    if ip not in network or str(ip) == self.lan_plan["server_ip"]:
                        raise ValueError("IP мультиметра должен отличаться от IP ПК и находиться в той же подсети.")
            resource_name = self.get_resource_name()
            if not resource_name:
                raise ValueError("Ресурс не найден.")
        except Exception as exc:
            QMessageBox.warning(self, "Подключение", str(exc))
            return
        is_lan = self.radio_lan.isChecked()
        self.set_lan_message(f"Проверка прибора (*IDN?): {resource_name}…")
        self.run_operation(
            lambda: open_instrument(self.rm, resource_name, require_ut8805e=is_lan),
            lambda result: self.instrument_connected(result, resource_name),
            lambda message: self.operation_failed(
                f"Не удалось завершить подключение к {resource_name}.\n{message}"),
        )

    def instrument_connected(self, result, resource_name):
        self.instrument, identity = result
        self.current_func = "VOLT:DC"
        self.is_connected = True
        self.btn_connect.setText("Отключиться")
        self.set_lan_message(f"Подключён {identity} ({resource_name})")
        try:
            self.change_range()
            self.change_speed()
            self.change_impedance()
        except Exception as exc:
            self.disconnect_instrument()
            self.operation_failed(str(exc))

    def disconnect_instrument(self):
        self.stop_measurement()
        if self.instrument:
            try:
                self.instrument.write("*UNREMOTE")
            except Exception:
                pass
            try:
                self.instrument.close()
            except Exception:
                pass
        self.instrument = None
        self.is_connected = False
        self.btn_connect.setText("Подключиться")
        self.update_controls()
        self.statusBar().showMessage("Отключено")

    def open_function_dialog(self):
        if not self.instrument: return
        dlg = FunctionDialog(self)
        if dlg.exec():
            self.current_func = "VOLT:DC"
            self.instrument.write("CONF:VOLT:DC")
            self.unit_label.setText("VDC")
            
            self.imp_check.setEnabled(True) 
            
            self.range_combo.setCurrentText("AUTO")
            self.change_range()

    def open_math_dialog(self):
        if not self.instrument: return
        dlg = MathDialog(self.instrument, self)
        dlg.exec()

    def open_options_dialog(self):
        dlg = OptionsDialog(self)
        dlg.spin_points.setValue(self.max_points)
        dlg.check_inf.setChecked(self.is_infinite)
        dlg.spin_rate.setValue(self.measure_interval / 1000.0) 
        dlg.check_skip.setChecked(self.skip_repeats)
        
        if dlg.exec():
            settings = dlg.get_settings()
            self.max_points = settings["max_points"]
            self.is_infinite = settings["infinite"]
            self.measure_interval = settings["interval"]
            self.skip_repeats = settings["skip_repeats"]

    def change_range(self):
        if not self.instrument: return
        rng = self.range_combo.currentText()
        if rng == "AUTO":
            self.instrument.write(f"{self.current_func}:RANG:AUTO ON")
        else:
            if "mV" in rng:
                val = float(rng.replace("mV", "")) * 1e-3
            else:
                val = float(rng.replace("V", ""))
            self.instrument.write(f"{self.current_func}:RANG {val}")

    def change_speed(self):
        if not self.instrument: return
        speed = self.speed_combo.currentText()
        self.instrument.write(f"{self.current_func}:NPLC {speed}")

    def change_impedance(self):
        if not self.instrument or self.current_func != "VOLT:DC": return
        state = "ON" if self.imp_check.isChecked() else "OFF"
        self.instrument.write(f"VOLT:DC:IMP:AUTO {state}")

    def clear_log(self):
        self.table.setRowCount(0)

    def save_log(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить лог", "", "Text Files (*.txt);;All Files (*)"
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    # Заголовок таблицы (ширина: №=6, Время=15, Значение=20)
                    f.write(f"{'№':>6} | {'Время':^15} | {'Значение':^20}\n")
                    f.write("-" * 46 + "\n")
                    
                    for row in range(self.table.rowCount()):
                        num = self.table.item(row, 0).text()
                        time_str = self.table.item(row, 1).text()
                        val = self.table.item(row, 2).text()
                        
                        # Форматируем строку с выравниванием
                        f.write(f"{num:>6} | {time_str:^15} | {val:>20}\n")
                
                QMessageBox.information(self, "Успех", "Лог сохранен в TXT")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить: {e}")

    def start_measurement(self):
        if not self.instrument or self.worker: return
        self.table.setRowCount(0)
        self.worker = MeasurementWorker(
            self.instrument, 
            interval_ms=self.measure_interval,
            max_points=self.max_points,
            infinite=self.is_infinite,
            skip_repeats=self.skip_repeats
        )
        self.worker.data_received.connect(self.update_display)
        self.worker.error_occurred.connect(self.on_worker_error)
        self.worker.finished_signal.connect(self.on_measurement_finished)
        self.worker.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def on_measurement_finished(self):
        self.stop_measurement()
        self.statusBar().showMessage("Опрос завершен по лимиту точек")

    def stop_measurement(self):
        if self.worker:
            self.worker.stop()
            self.worker = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def update_display(self, value, func):
        self.value_label.setText(f"{value:+.6f}")
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.table.setItem(row, 1, QTableWidgetItem(datetime.now().strftime("%H:%M:%S.%f")[:-3]))
        self.table.setItem(row, 2, QTableWidgetItem(f"{value:.9E}"))
        self.table.scrollToBottom()

    def on_worker_error(self, err):
        QMessageBox.critical(self, "Ошибка", err)
        self.stop_measurement()

    def closeEvent(self, event):
        if self.operation is not None:
            event.ignore()
            self.statusBar().showMessage("Дождитесь завершения операции, затем закройте окно.")
            return
        if self.lan_configurator.has_backup():
            event.ignore()
            self._close_after_restore = True
            self.restore_lan()
            return
        self.save_settings()
        self.disconnect_instrument()
        self.stop_dhcp()
        if self.rm:
            self.rm.close()
        event.accept()
