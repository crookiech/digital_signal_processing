"""Enumerate USB VISA instruments and COM ports without probing serial equipment."""

import threading

import pyvisa
from PyQt6.QtCore import QThread, pyqtSignal
from serial.tools import list_ports

from .transport import canonical_resource, claims, configure_transport


def is_bluetooth_port(port):
    hardware_id = (getattr(port, "hwid", "") or "").upper()
    description = (getattr(port, "description", "") or "").upper()
    return hardware_id.startswith("BTH") or "BLUETOOTH" in description


class DeviceDiscovery(QThread):
    snapshot = pyqtSignal(object)
    warning = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = None
        self._stop = threading.Event()
        self._usb = {}
        self._serial = {}
        self._excluded_serial = []
        self._known = {}
        self._known_lock = threading.Lock()

    def stop(self):
        self._stop.set()

    def resume(self):
        self._stop.clear()
        self.start()

    def remember(self, resource, baud):
        # Serial probing is permitted only after a successful user connection.
        with self._known_lock:
            self._known[canonical_resource(resource)] = int(baud)

    def _probe(self, entry, baud=9600):
        with claims.temporary(entry["resource"]) as acquired:
            if not acquired:
                return
            instrument = None
            try:
                instrument = self.manager.open_resource(
                    entry["resource"], open_timeout=1000
                )
                configure_transport(instrument, entry["resource"], baud)
                entry["identity"] = instrument.query("*IDN?").strip()
                entry["reachable"] = bool(entry["identity"])
            except Exception:
                entry["reachable"] = False
            finally:
                if instrument is not None:
                    try:
                        instrument.close()
                    except Exception:
                        pass

    def scan(self):
        try:
            ports = list_ports.comports()
            self._excluded_serial = [
                {"resource": canonical_resource(port.device), "excluded": True}
                for port in ports if is_bluetooth_port(port)
            ]
            self._serial = {
                canonical_resource(port.device): {
                    "resource": canonical_resource(port.device), "interface": "RS",
                    "label": port.device, "identity": "",
                } for port in ports if not is_bluetooth_port(port)
            }
        except Exception as exc:
            self.warning.emit(f"Поиск COM-портов: {exc}")
        try:
            if self.manager is None:
                self.manager = pyvisa.ResourceManager()
            # Filter at the backend: do not enumerate TCPIP/LAN resources.
            resources = self.manager.list_resources("USB?*::INSTR")
            current = {}
            for resource in resources:
                if self._stop.is_set():
                    break
                key = canonical_resource(resource)
                entry = dict(self._usb.get(key, {
                    "resource": key, "interface": "USB",
                    "label": "USB", "identity": "",
                }))
                entry.pop("reachable", None)
                self._probe(entry)
                current[key] = entry
            self._usb = current
        except Exception as exc:
            # Enumeration failure is not evidence that all instruments disappeared.
            self.warning.emit(f"Поиск USB: {exc}")
        with self._known_lock:
            known = dict(self._known)
        if self.manager is not None:
            for resource, entry in self._serial.items():
                if self._stop.is_set():
                    break
                if resource in known:
                    self._probe(entry, known[resource])
        return [*self._usb.values(), *self._serial.values(), *self._excluded_serial]

    def run(self):
        while not self._stop.is_set():
            self.snapshot.emit(self.scan())
            self._stop.wait(2)
