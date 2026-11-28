import pyvisa
import math
import logging
from time import sleep
from contextlib import contextmanager
from PyQt6.QtCore import QObject, pyqtSignal
from ..shared.transport import canonical_resource, configure_transport, parse_identity

logger = logging.getLogger(__name__)

VI_ATTR_ASRL_BAUD = 0x3FFF0001
VI_ATTR_ASRL_DATA_BITS = 0x3FFF0002
VI_ATTR_ASRL_PARITY = 0x3FFF0006
VI_ATTR_ASRL_STOP_BITS = 0x3FFF0003
VI_ATTR_ASRL_FLOW_CNTRL = 0x3FFF0005
VI_ASRL_PAR_NONE = 0
VI_ASRL_STOP_ONE = 10
VI_ASRL_FLOW_NONE = 16

class SerialWorker(QObject):
    shutdown_finished = pyqtSignal(object)
    response_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    connected = pyqtSignal(bool, str)
    connection_lost = pyqtSignal(str) 
    identity_received = pyqtSignal(str)
    state_received = pyqtSignal(bool, object)
    poll_finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.rm = None
        self.instr = None
        self._running = False

    def _get_rm(self):
        if self.rm is None:
            try:
                self.rm = pyvisa.ResourceManager('@ivi')
            except Exception:
                self.rm = pyvisa.ResourceManager('@py')
        return self.rm

    def open_port(self, port: str, baud: int = 0):
        try:
            rm = self._get_rm()
            if self.instr is not None:
                self.close_port()
            port = canonical_resource(port)
            self.instr = rm.open_resource(port, open_timeout=1500)

            is_serial = port.upper().startswith("ASRL")

            if is_serial:
                if baud <= 0:
                    baud = 9600
                try:
                    self.instr.set_visa_attribute(VI_ATTR_ASRL_BAUD, int(baud))
                    self.instr.set_visa_attribute(VI_ATTR_ASRL_DATA_BITS, 8)
                    self.instr.set_visa_attribute(VI_ATTR_ASRL_PARITY, VI_ASRL_PAR_NONE)
                    self.instr.set_visa_attribute(VI_ATTR_ASRL_STOP_BITS, VI_ASRL_STOP_ONE)
                    self.instr.set_visa_attribute(VI_ATTR_ASRL_FLOW_CNTRL, VI_ASRL_FLOW_NONE)
                except Exception:
                    if baud:
                        try:
                            self.instr.baud_rate = int(baud)
                        except Exception:
                            pass

            configure_transport(self.instr, port, baud or 9600)
            identity = self._exchange("*IDN?")
            if parse_identity(identity)[0] != "power_supply":
                raise ValueError(f"Это не UDP3305C: {identity}")
            state = self._read_state()
            self._running = True
            self.identity_received.emit(identity)
            self.connected.emit(True, port)
            self.state_received.emit(*state)
        except Exception as e:
            self.close_port()
            self.error_occurred.emit(f"не удалось подключиться к {port}: {e}")

    def close_port(self):
        self._running = False
        port = ""
        if self.instr is not None:
            try:
                port = self.instr.resource_name
            except Exception:
                pass
            try:
                self.instr.close()
            except Exception:
                pass
        self.instr = None
        self.connected.emit(False, port)

    def _lost(self, message):
        self.error_occurred.emit(message)
        self.close_port()
        self.connection_lost.emit(message)

    def _exchange(self, cmd: str) -> str:
        """One complete request in the instrument worker thread."""
        logger.debug("[QUERY] %s", cmd)
        self.instr.clear()
        self.instr.write(cmd)
        sleep(0.2)
        response = self.instr.read().strip()
        logger.debug("[RESPONSE] %s: %r", cmd, response)
        return response

    def _exchange_error(self, message, exc):
        # Timeouts and malformed replies do not prove that the cable was removed.
        if isinstance(exc, pyvisa.errors.VisaIOError):
            fatal = exc.error_code != pyvisa.constants.StatusCode.error_timeout
        else:
            fatal = isinstance(exc, (OSError, pyvisa.errors.InvalidSession))
        if fatal:
            self._lost(message)
        else:
            self.error_occurred.emit(message)

    def _write(self, cmd: str) -> bool:
        if not self.instr:
            self.error_occurred.emit("нет подключения")
            return False
        try:
            self.instr.write(cmd)
            return True
        except Exception as e:
            self._exchange_error(f"Ошибка записи '{cmd}': {e}", e)
            return False

    def _query(self, cmd: str) -> str:
        if not self.instr:
            self.error_occurred.emit("нет подключения")
            return ""
        try:
            return self._exchange(cmd)
        except Exception as e:
            self._exchange_error(f"Ошибка чтения '{cmd}': {e}", e)
            return ""

    @contextmanager
    def _select_channel3(self):
        # Keep selection and its unprefixed commands in the same worker operation.
        instrument = self.instr
        previous = self._exchange("INStrument?").upper()
        if previous not in {"CH1", "CH2", "CH3"}:
            raise ValueError(f"Некорректный выбранный канал: {previous!r}")
        changed = previous != "CH3"
        if changed:
            instrument.write("INStrument CH3")
            sleep(0.05)
        try:
            yield instrument
        finally:
            if changed:
                instrument.write(f"INStrument {previous}")

    def _set_channel_value(self, ch, command, value):
        if ch not in (1, 2, 3) or not math.isfinite(value):
            self.error_occurred.emit("Некорректный канал или значение")
            return
        maximum = (5.0 if command == "VOLTage" else 3.0) if ch == 3 else (
            30.0 if command == "VOLTage" else 5.0
        )
        if not 0 <= value <= maximum or (
            ch == 3 and command == "VOLTage"
            and not any(abs(value - allowed) < 1e-6 for allowed in (1.8, 2.5, 3.3, 5.0))
        ):
            self.error_occurred.emit(f"Недопустимое значение {command} для CH{ch}")
            return
        if self.instr is None:
            self.error_occurred.emit("нет подключения")
            return
        try:
            self.instr.write(f"CH{ch}:{command} {value:.3f}")
        except Exception as exc:
            self._exchange_error(f"Ошибка записи {command} CH{ch}: {exc}", exc)
            return
        self.poll_state()

    def set_voltage(self, ch: int, v: float):
        self._set_channel_value(ch, "VOLTage", v)

    def set_current(self, ch: int, i: float):
        self._set_channel_value(ch, "CURRent", i)

    def set_output(self, on: bool):
        if self._write(f"OUTPUT {'ON' if on else 'OFF'}"):
            self.poll_state()

    def _read_state(self):
        # UDP3000 Programming Manual: SYSTem:STATus?, bit 4 = output enabled.
        status = self._exchange("SYSTem:STATus?")
        value = int(status, 16)
        channels = []
        for channel in (1, 2):
            voltage = float(self._exchange(f"CH{channel}:VOLTage?"))
            current = float(self._exchange(f"CH{channel}:CURRent?"))
            if not all(math.isfinite(v) and v >= 0 for v in (voltage, current)):
                raise ValueError("Некорректные заданные U/I канала.")
            channels.append((channel, voltage, current))
        voltage = float(self._exchange("CH3:VOLTage?"))
        with self._select_channel3():
            current = float(self._exchange("CURRent?"))
            if not all(math.isfinite(v) and v >= 0 for v in (voltage, current)):
                raise ValueError("Некорректные заданные U/I канала CH3.")
            channels.append((3, voltage, current))
        return bool(value & 0x10), tuple(channels)

    def poll_state(self):
        try:
            if self.instr is not None:
                self.state_received.emit(*self._read_state())
        except Exception as exc:
            self._exchange_error(f"Не удалось проверить состояние источника: {exc}", exc)
        finally:
            self.poll_finished.emit()

    def shutdown(self):
        try:
            self.close_port()
        except Exception as exc:
            self.error_occurred.emit(f"Ошибка закрытия VISA: {exc}")
        finally:
            # The application releases shared VISA managers after all workers stop.
            self.shutdown_finished.emit(self.rm)
            self.rm = None
