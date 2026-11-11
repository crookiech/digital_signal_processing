import time
from datetime import datetime
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QLineEdit, QComboBox, 
                             QTableWidget, QTableWidgetItem, QMessageBox, 
                             QGroupBox, QRadioButton, QFormLayout, QHeaderView, 
                             QCheckBox, QFileDialog, QGridLayout)
from PyQt6.QtCore import Qt, QSettings
from dhcp_server import MiniDhcpServer
from scapy.arch.windows import get_windows_if_list # Для получения имен интерфейсов


import pyvisa
from instrument_worker import MeasurementWorker
from dialogs import OptionsDialog, FunctionDialog, MathDialog
from network_utils import get_pc_network_info

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
        
        self.measure_interval = 100 
        self.max_points = 10000     
        self.is_infinite = True
        self.skip_repeats = False
        self.current_func = "VOLT:DC" 
        
        self.settings = QSettings("MyLab", "UT8805E_App")

        self.init_ui()
        self.check_visa_backends()
        self.load_settings()

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
        self.ip_edit = QLineEdit("192.168.1.100")
        self.mask_edit = QLineEdit("255.255.255.0")
        self.gateway_edit = QLineEdit("192.168.1.1")

        self.btn_get_pc_ip = QPushButton("Взять с этого ПК")
        self.btn_get_pc_ip.clicked.connect(self.fill_pc_network_info)

        self.btn_start_dhcp = QPushButton("Запустить DHCP-сервер")
        self.btn_start_dhcp.clicked.connect(self.toggle_dhcp_server)

        self.btn_update_ip = QPushButton("Обновить IP из DHCP")
        self.btn_update_ip.clicked.connect(self.update_ip_from_dhcp)
        
        lan_form.addRow("IP Address:", self.ip_edit)
        lan_form.addRow("Маска:", self.mask_edit)
        lan_form.addRow("Шлюз:", self.gateway_edit)
        lan_form.addRow("", self.btn_get_pc_ip)
        lan_form.addRow("", self.btn_start_dhcp)
        lan_form.addRow("", self.btn_update_ip)
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
        main_layout.addLayout(left_panel, 1)

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
        self.ip_edit.setText(self.settings.value("lan/ip", "192.168.1.100"))
        self.mask_edit.setText(self.settings.value("lan/mask", "255.255.255.0"))
        self.gateway_edit.setText(self.settings.value("lan/gateway", "192.168.1.1"))
        
        iface = self.settings.value("conn/interface", "USB")
        if iface == "LAN": self.radio_lan.setChecked(True)
        elif iface == "RS232": self.radio_rs232.setChecked(True)
        else: self.radio_usb.setChecked(True)

    def save_settings(self):
        self.settings.setValue("lan/ip", self.ip_edit.text())
        self.settings.setValue("lan/mask", self.mask_edit.text())
        self.settings.setValue("lan/gateway", self.gateway_edit.text())
        
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

    def toggle_dhcp_server(self):
        if self.dhcp_server is None:
            # Запуск сервера
            try:
                from scapy.arch.windows import get_windows_if_list
                
                # Получаем IP-адрес, который введен в GUI
                pc_ip = self.ip_edit.text().strip()

                interfaces = get_windows_if_list()
                target_iface = None

                for iface in interfaces:
                    # В scapy ips — это список строк
                    if pc_ip in iface.get('ips', []):
                        target_iface = iface['name']
                        print(f"Найден интерфейс по IP: {target_iface}")
                        break
                
                # Если не нашли по IP, ищем по описанию (исключая WSL и виртуальные)
                if not target_iface:
                    for iface in interfaces:
                        desc = iface.get('description', '')
                        name = iface.get('name', '')
                        if ('Realtek' in desc or 'Intel' in desc) and 'WSL' not in name and 'Virtual' not in desc:
                            target_iface = name
                            print(f"Найден интерфейс по описанию: {target_iface} ({desc})")
                            break

                if not target_iface:
                    QMessageBox.warning(self, "Ошибка", "Не найден физический Ethernet-адаптер.")
                    return

                # Настройки пула (например, от 192.168.1.150 до 192.168.1.200)
                # Берем первые три октета из IP-адреса ПК
                pc_ip = self.ip_edit.text().strip().rsplit('.', 1)[0]
                pool_start = f"{pc_ip}.150"
                pool_end = f"{pc_ip}.200"
                mask = self.mask_edit.text().strip()
                gateway = self.gateway_edit.text().strip()

                self.dhcp_server = MiniDhcpServer(
                    interface=target_iface,
                    pool_start=pool_start,
                    pool_end=pool_end,
                    subnet_mask=mask,
                    gateway=gateway
                )
                self.dhcp_server.start()
                
                self.btn_start_dhcp.setText("Остановить DHCP")
                self.statusBar().showMessage(f"DHCP-сервер запущен на {target_iface} (Пул: {pool_start}-{pool_end})")
                
            except Exception as e:
                QMessageBox.critical(self, "Ошибка DHCP", f"Не удалось запустить сервер: {e}")
                self.dhcp_server = None
        else:
            # Остановка сервера
            self.dhcp_server.stop()
            self.dhcp_server = None
            self.btn_start_dhcp.setText("Запустить DHCP-сервер")
            self.statusBar().showMessage("DHCP-сервер остановлен.")

    def update_ip_from_dhcp(self):
        if self.dhcp_server and self.dhcp_server.leases:
            # Берем первый выданный IP (предполагая, что это мультиметр)
            last_ip = list(self.dhcp_server.leases.values())[-1]
            self.ip_edit.setText(last_ip)
            self.statusBar().showMessage(f"IP-адрес обновлен из DHCP: {last_ip}")
        else:
            QMessageBox.warning(self, "Ошибка", "DHCP-сервер не запущен или еще не выдал адреса.")

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
        if not self.is_connected:
            res_name = self.get_resource_name()
            if not res_name:
                QMessageBox.warning(self, "Ошибка", "Ресурс не найден.")
                return
            try:
                self.instrument = self.rm.open_resource(res_name)
                self.instrument.timeout = 5000
                self.instrument.read_termination = '\n'
                self.instrument.write_termination = '\n'
                
                self.current_func = "VOLT:DC"
                self.instrument.write("CONF:VOLT:DC")
                self.instrument.write("VOLT:DC:RANG:AUTO ON")
                self.instrument.write("VOLT:DC:IMP:AUTO ON") 
                
                self.btn_connect.setText("Отключиться")
                self.btn_start.setEnabled(True)
                self.is_connected = True
                self.statusBar().showMessage(f"Подключено: {res_name}")
                
                self.change_range()
                self.change_speed()
                self.change_impedance()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
        else:
            self.stop_measurement()
            try:
                self.instrument.write("*UNREMOTE")
                self.instrument.close()
            except: pass
            self.instrument = None
            self.btn_connect.setText("Подключиться")
            self.btn_start.setEnabled(False)
            self.is_connected = False
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
        self.save_settings()
        self.stop_measurement()

        if self.dhcp_server:
            self.dhcp_server.stop()
            self.dhcp_server = None
            
        if self.instrument:
            try:
                self.instrument.write("*UNREMOTE")
                self.instrument.close()
            except: pass
        event.accept()
    
    def fill_pc_network_info(self):
        ip, mask, gateway = get_pc_network_info()
        
        if ip == "Не определен":
            QMessageBox.warning(self, "Ошибка", "Не удалось определить сетевые настройки ПК. Проверьте подключение к сети.")
            return

        try:
            ip_parts = ip.split('.')
            recommended_device_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.100"
        except:
            recommended_device_ip = "192.168.1.100"

        self.ip_edit.setText(recommended_device_ip)
        self.mask_edit.setText(mask)
        self.gateway_edit.setText(gateway)
        
        msg = (
            f"Настройки вашего ПК:\n"
            f"IP: {ip}\n"
            f"Маска: {mask}\n"
            f"Шлюз: {gateway}\n\n"
            f"Для успешного подключения к мультиметру, убедитесь, что он находится в той же подсети.\n"
            f"Рекомендуется установить на мультиметре (в его меню):\n"
            f"IP: {recommended_device_ip}\n"
            f"Маска: {mask}\n"
            f"Шлюз: {gateway}\n\n"
        )
        QMessageBox.information(self, "Подсказка по сети", msg)