"""Device descriptions; demonstration statuses are independent of live connections."""

from dataclasses import dataclass
from enum import Enum


class DeviceState(Enum):
    DISCONNECTED = "Не подключено"
    CONNECTED = "Подключено"
    LOGGING = "Идёт запись логов"
    OUTPUT_ENABLED = "Выход включён"
    UNCONFIGURED = "Не настроено"
    READY = "Подключено и настроено"


@dataclass
class Device:
    key: str
    category: str
    name: str = ""
    state: DeviceState = DeviceState.READY
    available: bool = True
    is_demo: bool = False
    interface: str = ""
    is_preview: bool = False
    channel_values: tuple[tuple[int, float, float], ...] = ()
    kind: str = ""
    resource: str = ""
    serial_number: str = ""
    identity: str = ""
    present: bool = True
    reachable: bool | None = None
    baud_rate: int = 9600

    @property
    def display_name(self):
        title = self.name
        if self.interface and self.state != DeviceState.DISCONNECTED:
            title = f"{title} {self.interface}"
        if self.serial_number:
            title += f"\nS/N: {self.serial_number}"
        if self.channel_values and self.state != DeviceState.DISCONNECTED:
            channels = [
                f"CH{channel}: U = {voltage:.2f} В  I = {current:.3f} А"
                for channel, voltage, current in self.channel_values
            ]
            return "\n".join([title, *channels])
        return title


def demo_devices():
    return [
        Device("multimeter", "Мультиметр", name="Тест", is_demo=True),
        Device("converter", "ЦАП/АЦП", name="Тест", is_demo=True),
        Device("internal_dac", "Внутренний\nЦАП", name="Тест", available=False, is_demo=True),
        Device("power_supply", "Источник\nпитания", name="Тест", is_demo=True),
    ]


def multimeter_previews():
    """State samples and additional devices for testing list scrolling."""
    devices = [
        Device("multimeter_disconnected", "Мультиметр", name="Мультиметр 1",
               state=DeviceState.DISCONNECTED, is_preview=True),
        Device("multimeter_connected", "Мультиметр", name="Мультиметр 1",
               state=DeviceState.CONNECTED, interface="USB", is_preview=True),
        Device("multimeter_logging", "Мультиметр", name="Мультиметр 1",
               state=DeviceState.LOGGING, interface="USB", is_preview=True),
    ]
    states = (DeviceState.DISCONNECTED, DeviceState.CONNECTED, DeviceState.LOGGING)
    interfaces = ("USB", "LAN", "RS")
    for number in range(2, 8):
        devices.append(Device(
            f"multimeter_preview_{number}", "Мультиметр", name=f"Мультиметр {number}",
            state=states[(number - 2) % 3], interface=interfaces[(number - 2) % 3],
            is_preview=True,
        ))
    return devices


def power_supply_previews():
    """Power supply samples use illustrative channel values, not measurements."""
    values = ((1, 3.30, 0.010), (2, 5.00, 0.020), (3, 3.30, 0.100))
    devices = [
        Device("power_supply_disconnected", "Источник питания", name="Источник питания 1",
               state=DeviceState.DISCONNECTED, is_preview=True),
        Device("power_supply_connected", "Источник питания", name="Источник питания 1",
               state=DeviceState.CONNECTED, channel_values=values, is_preview=True),
        Device("power_supply_logging", "Источник питания", name="Источник питания 1",
               state=DeviceState.OUTPUT_ENABLED, channel_values=values, is_preview=True),
    ]
    states = (DeviceState.DISCONNECTED, DeviceState.CONNECTED, DeviceState.OUTPUT_ENABLED)
    for number in range(2, 8):
        state = states[(number - 2) % 3]
        devices.append(Device(
            f"power_supply_preview_{number}", "Источник питания",
            name=f"Источник питания {number}", state=state,
            channel_values=(
                ((1, 3.30 + number * 0.1, number * 0.005),
                 (2, 5.00 - number * 0.1, number * 0.004),
                 (3, 3.30, number * 0.010))
                if state != DeviceState.DISCONNECTED else ()
            ),
            is_preview=True,
        ))
    return devices
