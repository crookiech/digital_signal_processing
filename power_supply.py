from PyQt6.QtCore import QObject, pyqtSignal
from device_model import DeviceState, ChannelState
from device_session import DeviceSession
from device_window import DeviceWindow

class PowerSupplyController(QObject):
    connected = pyqtSignal(str, bool, str)
    state_changed = pyqtSignal(str)
    error = pyqtSignal(str, str)
    window_closed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sessions: dict[str, DeviceSession] = {}
        self._windows: dict[str, DeviceWindow] = {}

    def add_device(self, session_id: str, port: str = "", interface: str = "USB", baud: int = 0) -> None:
        if not session_id:
            self.error.emit("", "не задан session_id")
            return
        if session_id in self._sessions:
            self.error.emit(session_id, "устройство уже добавлено")
            return

        state = DeviceState(
            session_id=session_id,
            port=port,
            interface=interface,
            baud=baud,
        )
        sess = DeviceSession(state, parent=self)
        sess.connected.connect(self._on_connected)
        sess.response.connect(self._on_response)
        sess.error.connect(self._on_error)

        self._sessions[session_id] = sess
        if port:
            sess.open()

    def remove_device(self, session_id: str) -> None:
        win = self._windows.pop(session_id, None)
        if win is not None:
            win.close()
        sess = self._sessions.pop(session_id, None)
        if sess is not None:
            sess.shutdown()

    def shutdown_all(self) -> None:
        for sid in list(self._sessions.keys()):
            self.remove_device(sid)

    def get_state(self, session_id: str) -> DeviceState | None:
        sess = self._sessions.get(session_id)
        return sess.state if sess else None

    def get_all_states(self) -> dict[str, DeviceState]:
        return {sid: s.state for sid, s in self._sessions.items()}

    def open_settings_window(self, session_id: str) -> None:
        sess = self._sessions.get(session_id)
        if sess is None:
            self.error.emit(session_id, "устройство не найдено")
            return

        win = self._windows.get(session_id)
        if win is None:
            win = DeviceWindow(sess)
            win.destroyed.connect(
                lambda *_, s=session_id: self._on_window_destroyed(s))
            self._windows[session_id] = win

        win.apply_state(sess.state)
        win.show()
        win.raise_()
        win.activateWindow()

    def _on_window_destroyed(self, session_id: str):
        self._windows.pop(session_id, None)
        self.window_closed.emit(session_id)

    def _refresh_window(self, sid: str):
        win = self._windows.get(sid)
        sess = self._sessions.get(sid)
        if win is not None and sess is not None:
            win.apply_state(sess.state)

    def _on_connected(self, sid: str, ok: bool, port: str):
        sess = self._sessions.get(sid)
        if sess is None:
            return
        was_connected = sess.state.connected
        sess.state.connected = ok

        win = self._windows.get(sid)
        if win is not None:
            if ok:
                win.append_log(f"Подключено к {port}")
            elif was_connected:
                win.append_log(f"Отключено от {port}")
            else:
                win.append_log(f"Не удалось подключиться к {port}")

        self.connected.emit(sid, ok, port)
        if ok:
            sess.request_sn()
            for ch in (1, 2, 3):
                sess.request_voltage(ch)
                sess.request_current(ch)
        self._refresh_window(sid)
        self.state_changed.emit(sid)

    def _on_response(self, sid: str, msg: str):
        sess = self._sessions.get(sid)
        if sess is None:
            return
        st = sess.state

        try:
            tag, *rest = msg.split(":", 2)
            if tag == "SERIAL_NUMBER":
                st.serial_number = rest[0] if rest else ""
            elif tag == "VOLTAGE":
                ch, val = int(rest[0]), float(rest[1])
                st.channels.setdefault(ch, ChannelState()).voltage = val
            elif tag == "CURRENT":
                ch, val = int(rest[0]), float(rest[1])
                st.channels.setdefault(ch, ChannelState()).current = val
            else:
                self.error.emit(sid, msg)
                return
        except Exception:
            self.error.emit(sid, msg)
            return

        self.state_changed.emit(sid)
        self._refresh_window(sid)

    def _on_error(self, sid: str, msg: str):
        sess = self._sessions.get(sid)
        if sess is not None:
            win = self._windows.get(sid)
            if win is not None:
                win.append_log("Ошибка: " + msg)
            if ("нет подключения" in msg
                    or "Ошибка чтения" in msg
                    or "Ошибка записи" in msg):
                # sess.state.connected = False
                self._refresh_window(sid)
                self.state_changed.emit(sid)
        self.error.emit(sid, msg)
