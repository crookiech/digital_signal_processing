import signal
import sys
from pathlib import Path

# Support both `python main.py` and importing measurement_system.main.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "measurement_system"

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox, QInputDialog

from .main_menu import MainMenu
from .shared.appearance import configure_font
from .shared.sessions import SessionManager
from .shared.discovery import DeviceDiscovery
from .shared.registry import DeviceRegistry
from .shared.transport import parse_identity
from .shared.devices import DeviceState


def create_multimeter():
    from .multimeter.window import MultimeterWindow
    return MultimeterWindow()


def create_power_supply():
    from .power_supply.window import PowerSupplyWindow
    return PowerSupplyWindow()


class ApplicationController:
    def __init__(self, app, auto_discovery=True, registry=None):
        self.app = app
        self.menu = MainMenu()
        self.manager = SessionManager({
            "multimeter": create_multimeter,
            "power_supply": create_power_supply,
        }, self.menu)
        self.menu.device_requested.connect(self.open_device)
        self.menu.exit_requested.connect(self.shutdown)
        self.manager.shutdown_finished.connect(self.finish_shutdown)
        self.manager.shutdown_failed.connect(self.shutdown_failed)
        self.registry = registry if registry is not None else DeviceRegistry(parent=self.menu)
        self.registry.changed.connect(self.menu.update_device)
        self.registry.removed.connect(self.menu.remove_device)
        self.registry.disappeared.connect(self.device_unavailable)
        self._windows = {}
        self._shutting_down = False
        self._auto_discovery = auto_discovery
        self.discovery = DeviceDiscovery(self.menu)
        self.discovery.snapshot.connect(self._apply_snapshot)
        self.discovery.warning.connect(self.menu.statusBar().showMessage)
        self.discovery.finished.connect(self._discovery_stopped)
        for device in self.registry.devices.values():
            self.menu.update_device(device)
            if device.kind and device.resource:
                self.discovery.remember(device.resource, device.baud_rate)
        if auto_discovery:
            self.discovery.start()

    def open_device(self, key):
        try:
            if key not in self.registry.devices:
                self.manager.open_device(key)
                return
            device = self.registry.devices[key]
            if not device.present or device.reachable is False:
                QMessageBox.information(
                    self.menu, "Подключение", "Устройство не подключено"
                )
                return
            kind = device.kind
            if not kind:
                choice, accepted = QInputDialog.getItem(
                    self.menu, "Тип устройства",
                    f"{device.name}\nВыберите интерфейс прибора:",
                    ["Мультиметр", "Источник питания"], 0, False,
                )
                if not accepted:
                    return
                kind = "multimeter" if choice == "Мультиметр" else "power_supply"
            session_key = f"{key}:{kind}"
            self.manager.register(
                session_key, lambda: self._create_window(key, kind)
            )
            window = self.manager.open_device(session_key)
            # A retained USB card can acquire a different VISA address after replug.
            if window is not None and not getattr(
                    window, "is_connected", getattr(window, "_connected", False)):
                window.bound_device = device
                if kind == "power_supply":
                    window.refresh_ports()
        except Exception as exc:
            QMessageBox.critical(self.menu, "Не удалось открыть прибор", str(exc))

    def _apply_snapshot(self, entries):
        if not self._shutting_down:
            self.registry.apply_snapshot(entries)

    def _create_window(self, key, kind):
        device = self.registry.devices[key]
        if kind == "multimeter":
            from .multimeter.window import MultimeterWindow
            window = MultimeterWindow(device)
        else:
            from .power_supply.window import PowerSupplyWindow
            window = PowerSupplyWindow(device)
        window.state_changed.connect(
            lambda connected, identity, active, channels:
            self._device_state(window._registry_key, window,
                               connected, identity, active, channels)
        )
        window._registry_key = key
        window.identity_validator = (
            lambda identity: self._validate_identity(window._registry_key, identity)
        )
        window.connection_lost.connect(
            lambda: self._connection_lost(window._registry_key)
        )
        self._windows.setdefault(key, []).append(window)
        return window

    def _validate_identity(self, key, identity):
        kind, serial = parse_identity(identity)
        if serial and any(
            device.key != key and device.kind == kind
            and device.serial_number == serial
            and device.state != DeviceState.DISCONNECTED
            for device in self.registry.devices.values()
        ):
            raise ValueError("Этот прибор уже подключён через другое окно.")

    def _device_state(self, key, window, connected, identity, active, channels):
        if key not in self.registry.devices:
            return
        if connected and not self.registry.devices[key].present:
            window.device_unavailable()
            return
        if not connected and any(
            other is not window and getattr(
                other, "is_connected", getattr(other, "_connected", False)
            ) for other in self._windows.get(key, [])
        ):
            return
        if connected:
            self.registry.devices[key].baud_rate = int(window.baud_combo.currentText())
        try:
            device = self.registry.connection(key, connected, identity, active, channels)
        except ValueError as exc:
            if hasattr(window, "disconnect_instrument"):
                window.disconnect_instrument()
            else:
                window.sig_close.emit()
            window.statusBar().showMessage(str(exc))
            return
        if device.key != key:
            kind = device.kind
            source = self.manager.sessions.pop(f"{key}:{kind}", None)
            previous = self.manager.sessions.get(f"{device.key}:{kind}")
            if previous is not None and previous is not source:
                self.manager.sessions[f"retired:{id(previous)}"] = previous
            if source is not None:
                source.factory = lambda key=device.key, kind=kind: self._create_window(key, kind)
                self.manager.sessions[f"{device.key}:{kind}"] = source
            self._windows.get(key, []).remove(window)
            self._windows.setdefault(device.key, []).append(window)
            window._registry_key = device.key
            window.bound_device = device
        window.setWindowTitle(device.name)
        if connected:
            baud = int(window.baud_combo.currentText())
            self.discovery.remember(device.resource, baud)

    def _connection_lost(self, key):
        if key not in self.registry.devices:
            return
        device = self.registry.devices[key]
        device.reachable = False
        self.registry.changed.emit(device)

    def device_unavailable(self, key):
        for window in self._windows.get(key, []):
            window.device_unavailable()

    def shutdown(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        self.menu.setEnabled(False)
        self.menu.statusBar().showMessage("Завершение работы приборов…")
        self.discovery.stop()
        if not self.discovery.isRunning():
            self._discovery_stopped()

    def _discovery_stopped(self):
        if self._shutting_down:
            if self.discovery.manager is not None:
                self.manager.extra_managers.append(self.discovery.manager)
                self.discovery.manager = None
            self.manager.shutdown()

    def finish_shutdown(self):
        self.menu.exit_allowed = True
        self.menu.close()
        self.app.quit()

    def shutdown_failed(self, message):
        self._shutting_down = False
        self.menu.setEnabled(True)
        if self._auto_discovery and not self.discovery.isRunning():
            self.discovery.resume()
        self.menu.statusBar().showMessage("Завершение отменено. Повторите после восстановления Ethernet.")
        QMessageBox.warning(self.menu, "Завершение приложения", message)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Measurement System")
    configure_font(app)
    app.setQuitOnLastWindowClosed(False)
    controller = ApplicationController(app)
    signal.signal(signal.SIGINT, lambda *_: controller.menu.close())
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(200)
    controller.menu.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
