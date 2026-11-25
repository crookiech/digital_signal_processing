"""Retained physical-device cards. Connection state is never restored as live."""

import json
from uuid import uuid4

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from .devices import Device, DeviceState
from .transport import canonical_resource, parse_identity, port_label


class DeviceRegistry(QObject):
    changed = pyqtSignal(object)
    disappeared = pyqtSignal(str)
    removed = pyqtSignal(str)

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else QSettings(
            "MyLab", "MeasurementSystem"
        )
        self.devices = {}
        try:
            records = json.loads(self.settings.value("devices", "[]"))
            for record in records:
                device = Device(**record, state=DeviceState.DISCONNECTED, present=False)
                self.devices[device.key] = device
        except (ValueError, TypeError, KeyError):
            self.devices.clear()

    def save(self):
        fields = ("key", "category", "name", "kind", "resource", "interface",
                  "serial_number", "identity", "baud_rate")
        records = [{field: getattr(device, field) for field in fields}
                   for device in self.devices.values()]
        self.settings.setValue("devices", json.dumps(records, ensure_ascii=False))
        self.settings.sync()

    def find_resource(self, resource):
        key = canonical_resource(resource)
        matches = [d for d in self.devices.values()
                   if canonical_resource(d.resource) == key]
        return next((d for d in matches if d.present),
                    matches[0] if matches else None)

    def resolve_identity(self, device, identity):
        kind, serial = parse_identity(identity)
        if not kind:
            raise ValueError(f"Неподдерживаемая модель прибора: {identity}")
        target = next((d for d in self.devices.values()
                       if serial and d.serial_number == serial and d.kind == kind
                       and d.key != device.key), None)
        changed_instrument = (
            device.serial_number and serial and device.serial_number != serial
        ) or (device.kind and device.kind != kind)
        if target is None and changed_instrument:
            target = Device(uuid4().hex, "Мультиметр",
                            state=DeviceState.DISCONNECTED)
            self.devices[target.key] = target
        if target is None:
            return device
        if target.state != DeviceState.DISCONNECTED:
            raise ValueError("Этот прибор уже подключён через другое окно.")
        target.resource = device.resource
        target.interface = device.interface
        target.baud_rate = device.baud_rate
        target.present = device.present
        if device.kind:
            # Keep the previous instrument, but it no longer occupies this port.
            device.resource = ""
            device.present = False
            device.state = DeviceState.DISCONNECTED
            self.changed.emit(device)
        else:
            self.devices.pop(device.key)
            self.removed.emit(device.key)
        return target

    def identify(self, device, identity):
        kind, serial = parse_identity(identity)
        if not kind:
            raise ValueError(f"Неподдерживаемая модель прибора: {identity}")
        if not device.kind or device.kind != kind:
            number = 1 + max((
                int(d.name.rsplit(" ", 1)[-1]) for d in self.devices.values()
                if d.kind == kind and d.name.rsplit(" ", 1)[-1].isdigit()
            ), default=0)
            device.name = f"{'Мультиметр' if kind == 'multimeter' else 'Источник питания'} {number}"
        device.kind = kind
        device.category = "Мультиметр" if kind == "multimeter" else "Источник питания"
        device.serial_number = serial
        device.identity = identity
        self.save()

    def apply_snapshot(self, entries):
        seen = set()
        for entry in entries:
            resource = canonical_resource(entry["resource"])
            if entry.get("excluded"):
                for device in list(self.devices.values()):
                    if canonical_resource(device.resource) == resource:
                        device.present = False
                        device.state = DeviceState.DISCONNECTED
                        self.disappeared.emit(device.key)
                        self.devices.pop(device.key, None)
                        self.removed.emit(device.key)
                continue
            identity = entry.get("identity", "")
            device = self.find_resource(resource)
            # USB serial identity lets a retained card follow a changed VISA address.
            if device is None and identity:
                try:
                    kind, serial = parse_identity(identity)
                    if serial and kind:
                        device = next((d for d in self.devices.values()
                                       if d.kind == kind and d.serial_number == serial
                                       and not d.present), None)
                except ValueError:
                    pass
            if device is None:
                label = port_label(resource) if entry["interface"] == "RS" else "USB"
                device = Device(
                    uuid4().hex, "Мультиметр",
                    name=f"Неопределённое устройство · {label}",
                    state=DeviceState.DISCONNECTED,
                )
                self.devices[device.key] = device
            device.resource = resource
            device.interface = entry["interface"]
            if identity and device.state == DeviceState.DISCONNECTED:
                try:
                    device = self.resolve_identity(device, identity)
                    self.identify(device, identity)
                except ValueError:
                    pass
            if not device.present:
                device.reachable = None
            device.present = True
            if "reachable" in entry and (device.kind or entry["reachable"]):
                device.reachable = entry["reachable"]
            seen.add(device.key)
            self.changed.emit(device)
        for device in list(self.devices.values()):
            if device.key not in seen and device.present:
                device.present = False
                device.state = DeviceState.DISCONNECTED
                self.disappeared.emit(device.key)
                self.changed.emit(device)
        self.save()

    def connection(self, key, connected, identity="", active=False, channels=()):
        device = self.devices[key]
        if connected:
            device = self.resolve_identity(device, identity)
            self.identify(device, identity)
            device.present = True
            device.reachable = True
        active_state = (
            DeviceState.OUTPUT_ENABLED if device.kind == "power_supply"
            else DeviceState.LOGGING
        )
        device.state = (active_state if active else DeviceState.CONNECTED
                        ) if connected else DeviceState.DISCONNECTED
        if channels:
            device.channel_values = tuple(channels)
        self.changed.emit(device)
        return device
