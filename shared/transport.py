"""USB/serial identity and ownership, with no LAN discovery or configuration."""

import re
import threading
from contextlib import contextmanager

from pyvisa import constants


def canonical_resource(resource):
    value = resource.strip()
    match = re.fullmatch(r"(?:COM|ASRL)(\d+)(?:::INSTR)?", value.upper())
    return f"ASRL{int(match[1])}::INSTR" if match else value


def port_label(resource):
    match = re.fullmatch(r"ASRL(\d+)::INSTR", canonical_resource(resource))
    return f"COM{match[1]}" if match else resource


def parse_identity(identity):
    fields = [value.strip() for value in identity.split(",")]
    if len(fields) < 2 or not fields[1]:
        raise ValueError("Некорректный ответ на *IDN?.")
    model = fields[1].upper()
    kind = {"UT8805": "multimeter", "UT8805E": "multimeter",
            "UDP3305C": "power_supply"}.get(model, "")
    serial = fields[2] if len(fields) > 2 else ""
    if serial.upper() in {"", "0", "NONE", "N/A", "UNKNOWN"}:
        serial = ""
    return kind, serial


def configure_transport(instrument, resource, baud=9600):
    resource = canonical_resource(resource)
    instrument.timeout = 1500
    instrument.write_termination = "\n"
    instrument.read_termination = (
        None if resource.startswith("USB") and resource.endswith("::INSTR") else "\n"
    )
    if resource.startswith("ASRL"):
        instrument.baud_rate = int(baud)
        instrument.data_bits = 8
        instrument.parity = constants.Parity.none
        instrument.stop_bits = constants.StopBits.one
        instrument.flow_control = constants.ControlFlow.none


class ResourceClaims:
    """Discovery and device windows must never access the same port concurrently."""

    def __init__(self):
        self._lock = threading.Lock()
        self._owners = {}

    def acquire(self, resource, owner):
        key = canonical_resource(resource)
        with self._lock:
            if key in self._owners and self._owners[key] is not owner:
                return False
            self._owners[key] = owner
            return True

    def release(self, resource, owner):
        key = canonical_resource(resource)
        with self._lock:
            if self._owners.get(key) is owner:
                self._owners.pop(key, None)

    @contextmanager
    def temporary(self, resource):
        owner = object()
        acquired = self.acquire(resource, owner)
        try:
            yield acquired
        finally:
            if acquired:
                self.release(resource, owner)


claims = ResourceClaims()


class SynchronizedInstrument:
    """Keep a query's write/read pair together while UI settings change."""

    def __init__(self, instrument):
        self._instrument = instrument
        self._lock = threading.RLock()

    def __getattr__(self, name):
        return getattr(self._instrument, name)

    def query(self, command):
        with self._lock:
            return self._instrument.query(command)

    def write(self, command):
        with self._lock:
            return self._instrument.write(command)

    def close(self):
        with self._lock:
            return self._instrument.close()


def open_meter(manager, resource, baud=9600):
    instrument = None
    try:
        instrument = manager.open_resource(resource, open_timeout=1500)
        configure_transport(instrument, resource, baud)
        identity = instrument.query("*IDN?").strip()
        if parse_identity(identity)[0] != "multimeter":
            raise ValueError(f"Это не поддерживаемый мультиметр: {identity}")
        # The window restores its profile only after validating the model.
        return SynchronizedInstrument(instrument), identity
    except Exception:
        if instrument is not None:
            instrument.close()
        raise
