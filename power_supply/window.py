from PyQt6.QtCore import Qt, pyqtSignal
from ..shared.transport import claims, port_label

from .gui import MainWindow
from .styles import GLOBAL_QSS


class PowerSupplyWindow(MainWindow):
    sig_shutdown = pyqtSignal()
    sig_poll = pyqtSignal()
    state_changed = pyqtSignal(bool, str, bool, object)
    connection_lost = pyqtSignal()

    def __init__(self, device=None):
        self.bound_device = device
        self.identity = ""
        self.output_enabled = False
        self.channel_values = ()
        self._poll_pending = False
        self._claimed_resource = ""
        super().__init__()
        self.shutdown_complete = False
        self._shutdown_started = False
        self._worker_rm = None
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setStyleSheet(GLOBAL_QSS)
        # The original application-wide shortcut must not close a hidden window.
        self.shortcut_q.setContext(Qt.ShortcutContext.WindowShortcut)
        self.sig_shutdown.connect(self.worker.shutdown)
        self.worker.shutdown_finished.connect(self._remember_worker_manager)
        self.worker.shutdown_finished.connect(self.thread.quit)
        self.thread.finished.connect(self._shutdown_finished)
        self.thread.finished.connect(self.worker.deleteLater)
        self.worker.identity_received.connect(self._identity_received)
        self.worker.state_received.connect(self._state_received)
        self.worker.poll_finished.connect(self._poll_finished)
        self.worker.connection_lost.connect(self.connection_lost)
        self.sig_poll.connect(self.worker.poll_state)
        self.poll_timer.setInterval(1500)
        self.poll_timer.timeout.connect(self._poll)
        if device is not None:
            self.setWindowTitle(device.name)
            self.cmb_iface.setCurrentIndex(1 if device.interface == "RS" else 0)
            self.refresh_ports()
            self.baud_combo.setCurrentText(str(device.baud_rate))
            self.cmb_iface.setEnabled(False)
            self.port_combo.setEnabled(False)

    def refresh_ports(self):
        if self.bound_device is None:
            return super().refresh_ports()
        if not hasattr(self, "port_combo"):
            return
        self.port_combo.clear()
        resource = self.bound_device.resource
        self.port_combo.addItem(port_label(resource), resource)

    def on_connect_toggled(self, checked):
        if checked:
            resource = self.port_combo.currentData()
            if resource and not claims.acquire(resource, self):
                self.btn_connect.blockSignals(True)
                self.btn_connect.setChecked(False)
                self.btn_connect.blockSignals(False)
                self.append_log("Порт занят другим окном или поиском USB. Повторите подключение.")
                return
            self._claimed_resource = resource or ""
            self.btn_connect.setEnabled(False)
        super().on_connect_toggled(checked)

    def on_connected(self, ok, port):
        super().on_connected(ok, port)
        self.btn_connect.setEnabled(True)
        self.baud_combo.setEnabled(not ok)
        if not ok:
            claims.release(self._claimed_resource, self)
            self._claimed_resource = ""
            self.output_enabled = False
            self._poll_pending = False
            self.btn_output.blockSignals(True)
            self.btn_output.setChecked(False)
            self.btn_output.blockSignals(False)
            self.btn_output.setText("Включить выход")
        self.state_changed.emit(ok, self.identity, self.output_enabled, self.channel_values)

    def _identity_received(self, identity):
        self.identity = identity

    def _state_received(self, output, channels):
        self.output_enabled = output
        self.channel_values = tuple(channels)
        self.btn_output.blockSignals(True)
        self.btn_output.setChecked(output)
        self.btn_output.blockSignals(False)
        self.btn_output.setText("Выключить выход" if output else "Включить выход")
        self.state_changed.emit(self._connected, self.identity, output, channels)

    def _poll_finished(self):
        self._poll_pending = False

    def _poll(self):
        if self._connected and not self._poll_pending and not self._shutdown_started:
            self._poll_pending = True
            self.sig_poll.emit()

    def device_unavailable(self):
        self.poll_timer.stop()
        self.sig_close.emit()

    def closeEvent(self, event):
        # Retain the session, settings, and connection when its window is closed.
        event.accept()

    def advance_shutdown(self):
        if not self._shutdown_started:
            self._shutdown_started = True
            self.setEnabled(False)
            self.poll_timer.stop()
            # Queued behind outstanding commands; no forced thread termination.
            self.sig_shutdown.emit()
        return self.shutdown_complete

    def _shutdown_finished(self):
        self.shutdown_complete = True
        self.close()

    def _remember_worker_manager(self, manager):
        self._worker_rm = manager

    def resource_managers(self):
        return (self.rm, self._worker_rm)

    def release_manager_references(self):
        self.rm = None
        self._worker_rm = None
