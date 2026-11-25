"""Application-owned sessions retain instrument windows and their working state."""

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class InstrumentSession(QObject):
    def __init__(self, factory, parent=None):
        super().__init__(parent)
        self.factory = factory
        self.window = None

    def show(self):
        if self.window is None or self.window.shutdown_complete:
            self.window = self.factory()
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()
        return self.window


class SessionManager(QObject):
    shutdown_finished = pyqtSignal()
    shutdown_failed = pyqtSignal(str)

    def __init__(self, factories, parent=None):
        super().__init__(parent)
        self.sessions = {
            key: InstrumentSession(factory, self) for key, factory in factories.items()
        }
        self.closing = False
        self.extra_managers = []
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._advance_shutdown)

    def open_device(self, key):
        if not self.closing and key in self.sessions:
            return self.sessions[key].show()
        return None

    def register(self, key, factory):
        if key not in self.sessions:
            self.sessions[key] = InstrumentSession(factory, self)

    def shutdown(self):
        if self.closing:
            return
        self.closing = True
        self.timer.start()
        self._advance_shutdown()

    def _advance_shutdown(self):
        try:
            complete = True
            for session in self.sessions.values():
                if session.window is not None:
                    # Visit every session even if another one is still busy.
                    ready = session.window.advance_shutdown()
                    complete = ready and complete
            if complete:
                # PyVISA can return the same manager to several instrument windows.
                # Release it only after all I/O has finished, and only once.
                managers = {
                    id(manager): manager
                    for session in self.sessions.values()
                    if session.window is not None
                    for manager in session.window.resource_managers()
                    if manager is not None
                }
                managers.update({id(manager): manager for manager in self.extra_managers
                                 if manager is not None})
                for manager in managers.values():
                    manager.close()
                for session in self.sessions.values():
                    if session.window is not None:
                        session.window.release_manager_references()
                self.timer.stop()
                self.shutdown_finished.emit()
        except Exception as exc:
            self.timer.stop()
            self.closing = False
            self.shutdown_failed.emit(str(exc))
