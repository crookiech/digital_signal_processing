from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QMessageBox
from ..shared.transport import claims, open_meter, parse_identity, port_label

from .main_window import MultimeterApp


class MultimeterWindow(MultimeterApp):
    state_changed = pyqtSignal(bool, str, bool, object)
    connection_lost = pyqtSignal()

    def __init__(self, device=None):
        self.bound_device = device
        self.identity = ""
        self._claimed_resource = ""
        self._unavailable = False
        self._disconnecting = False
        super().__init__()
        self.shutdown_complete = False
        self._restoring_for_exit = False
        self._shutdown_error = None
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        if device is not None:
            self.setWindowTitle(device.name)
            self.baud_combo = QComboBox()
            self.baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
            self.baud_combo.setCurrentText(
                self.settings.value(f"serial_baud/{device.key}", str(device.baud_rate))
            )
            self.serial_group.layout().addRow("Бод:", self.baud_combo)
            if device.interface == "RS":
                self.radio_rs232.setChecked(True)
            else:
                self.radio_usb.setChecked(True)
            self.refresh_com_ports()
            self.update_controls()
        self.health_timer = QTimer(self)
        self.health_timer.setInterval(2000)
        self.health_timer.timeout.connect(self._check_connection)
        if device is not None:
            self.health_timer.start()

    def refresh_adapters(self):
        if self.bound_device is None:
            super().refresh_adapters()

    def refresh_com_ports(self):
        if self.bound_device is None:
            return super().refresh_com_ports()
        self.combo_com.clear()
        self.combo_com.addItem(port_label(self.bound_device.resource))

    def update_controls(self):
        super().update_controls()
        if self.bound_device is not None:
            for widget in (self.radio_usb, self.radio_lan, self.radio_rs232,
                           self.combo_com, self.btn_refresh_com):
                widget.setEnabled(False)
            if hasattr(self, "baud_combo"):
                self.baud_combo.setEnabled(
                    not self.is_connected and self.operation is None
                )

    def get_resource_name(self):
        if self.bound_device is not None:
            return self.bound_device.resource
        return super().get_resource_name()

    def get_device_id(self):
        if self.bound_device is not None:
            # Stable serial-based profile, with a retained card ID as fallback.
            serial = parse_identity(self.identity)[1] if self.identity else ""
            return f"physical_{serial or self.bound_device.key}"
        return super().get_device_id()

    def toggle_connection(self):
        if self.bound_device is None:
            if not self.is_connected and not self.radio_lan.isChecked():
                resource = self.get_resource_name()
                if resource and not claims.acquire(resource, self):
                    QMessageBox.information(self, "Подключение", "Порт занят другим окном.")
                    return
                self._claimed_resource = resource or ""
            return super().toggle_connection()
        if self.is_connected:
            self.disconnect_instrument()
            return
        if self.operation is not None:
            return
        if not self.bound_device.present:
            QMessageBox.information(self, "Подключение", "Устройство не подключено")
            return
        resource = self.get_resource_name()
        if not claims.acquire(resource, self):
            QMessageBox.information(
                self, "Подключение",
                "Порт занят другим окном или поиском USB. Повторите подключение.",
            )
            return
        self._claimed_resource = resource
        self._unavailable = False
        baud = int(self.baud_combo.currentText())
        self.settings.setValue(f"serial_baud/{self.bound_device.key}", str(baud))
        self.run_operation(
            lambda: open_meter(self.rm, resource, baud),
            lambda result: self.instrument_connected(result, resource),
            self._connection_failed,
        )

    def _connection_failed(self, message):
        claims.release(self._claimed_resource, self)
        self._claimed_resource = ""
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "Подключение", message)

    def instrument_connected(self, result, resource_name):
        self.identity = result[1]
        if self.bound_device is not None and hasattr(self, "identity_validator"):
            try:
                self.identity_validator(self.identity)
            except ValueError as exc:
                result[0].close()
                self._connection_failed(str(exc))
                return
        super().instrument_connected(result, resource_name)
        if self._unavailable:
            self.disconnect_instrument()
        self._publish_state()

    def _publish_state(self):
        if self._disconnecting:
            return
        self.state_changed.emit(
            self.is_connected, self.identity,
            self.is_connected and self.is_logging_to_file, (),
        )

    def toggle_logging_to_file(self):
        super().toggle_logging_to_file()
        self._publish_state()

    def stop_file_logging(self):
        super().stop_file_logging()
        self._publish_state()

    def disconnect_instrument(self):
        self._disconnecting = True
        try:
            if self.bound_device is not None:
                self.stop_file_logging()
            super().disconnect_instrument()
        finally:
            self._disconnecting = False
        claims.release(self._claimed_resource, self)
        self._claimed_resource = ""
        self._publish_state()

    def device_unavailable(self):
        self._unavailable = True
        if self.operation is None:
            self.disconnect_instrument()
            self.statusBar().showMessage("Устройство не подключено")

    def operation_finished(self):
        super().operation_finished()
        if self._unavailable and self.is_connected:
            self.disconnect_instrument()

    def _check_connection(self):
        if (not self.is_connected or self.worker is not None
                or self.operation is not None or self.shutdown_complete):
            return
        # Idle devices also need a liveness check; active polling supplies errors itself.
        self.centralWidget().setEnabled(False)
        self.run_operation(
            lambda: self.instrument.query("*IDN?").strip(),
            self._health_received,
            self._health_failed,
        )

    def _health_received(self, identity):
        self.centralWidget().setEnabled(True)
        if identity != self.identity:
            self._health_failed("Изменился ответ прибора. Подключитесь заново.")

    def _health_failed(self, message):
        self.centralWidget().setEnabled(True)
        self.disconnect_instrument()
        self.connection_lost.emit()
        self.statusBar().showMessage(f"Связь с прибором потеряна: {message}")

    def on_worker_error(self, message):
        if self.bound_device is None:
            return super().on_worker_error(message)
        self._health_failed(message)

    def closeEvent(self, event):
        # Closing only dismisses the view; the application owns the session.
        self.save_device_profile()
        self.save_settings()
        event.accept()

    def operation_failed(self, message):
        if not self.is_connected:
            claims.release(self._claimed_resource, self)
            self._claimed_resource = ""
        if self._restoring_for_exit:
            self._shutdown_error = message
            self.set_lan_message(message)
            return
        super().operation_failed(message)

    def advance_shutdown(self):
        if self.shutdown_complete:
            return True
        if self._shutdown_error:
            message = self._shutdown_error
            self._shutdown_error = None
            self._restoring_for_exit = False
            raise RuntimeError(f"Не удалось восстановить Ethernet:\n{message}")
        if self.operation is not None:
            return False
        if self.lan_configurator.has_backup():
            if self._restoring_for_exit:
                self._restoring_for_exit = False
                raise RuntimeError("Исходные настройки Ethernet пока не восстановлены.")
            self._restoring_for_exit = True
            self.restore_lan()
            return False
        self.stop_file_logging()
        self.health_timer.stop()
        self.save_settings()
        self.disconnect_instrument()
        self.stop_dhcp()
        self.shutdown_complete = True
        self.close()
        return True

    def resource_managers(self):
        return (self.rm,)

    def release_manager_references(self):
        self.rm = None
