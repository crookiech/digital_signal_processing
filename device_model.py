from dataclasses import dataclass, field, asdict
from typing import Dict

@dataclass
class ChannelState:
    voltage: float = 0.0
    current: float = 0.0

@dataclass
class DeviceState:
    session_id: str = ""
    serial_number: str = ""
    port: str = ""
    interface: str = ""
    baud: int = 0
    connected: bool = False
    output_on: bool = False
    channels: Dict[int, ChannelState] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DeviceState":
        ch = {
            int(k): ChannelState(**v)
            for k, v in (d.get("channels") or {}).items()
        }
        return cls(
            session_id=d.get("session_id", ""),
            serial_number=d.get("serial_number", ""),
            port=d.get("port", ""),
            interface=d.get("interface", ""),
            baud=d.get("baud", 0),
            connected=d.get("connected", False),
            output_on=d.get("output_on", False),
            channels=ch,
        )