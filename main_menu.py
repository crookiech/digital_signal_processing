from PyQt6.QtCore import QEvent, Qt, pyqtSignal, QSize, QRect
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton, QScrollArea,
    QVBoxLayout, QWidget, QStyle, QStyleOptionButton, QStylePainter, QSizePolicy,
)

from .shared.devices import (
    DeviceState, demo_devices, multimeter_previews, power_supply_previews,
)


class DeviceCard(QPushButton):
    COLORS = {
        DeviceState.DISCONNECTED: ("#70757c", "#d7dbe0", "#c6ccd3"),
        DeviceState.CONNECTED: ("#b58b00", "#ffe071", "#ffd44a"),
        DeviceState.LOGGING: ("#219653", "#78d99b", "#5dce86"),
        DeviceState.OUTPUT_ENABLED: ("#219653", "#78d99b", "#5dce86"),
        DeviceState.UNCONFIGURED: ("#e0ba00", "#fffdf0", "#fff5bf"),
        DeviceState.READY: ("#20b455", "#f7fff9", "#def7e6"),
    }

    def __init__(self, device, parent=None):
        super().__init__(device.display_name, parent)
        self.device = device
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumHeight(90 if device.channel_values else 52)
        self.setEnabled(device.available)
        if device.available:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_state(device.state)

    def set_state(self, state):
        self.device.state = state
        self.setText(self.device.display_name)
        self.setAccessibleName(f"{self.device.category.replace(chr(10), ' ')}: {self.text()}")
        border, background, hover = self.COLORS[state]
        text_color = "#000000"
        if self.device.is_demo:
            border, background, hover = "#000000", "#ffa500", "#ffb733"
            text_color = "#000000"
        tooltip = state.value
        if self.device.is_demo:
            tooltip = "Тестовое устройство для отладки"
        if self.device.is_preview:
            tooltip += ". Образец оформления, без связи с прибором."
        if not self.device.available:
            tooltip = "Интерфейс будет добавлен позже"
        self.setToolTip(tooltip)
        self.setStyleSheet(f"""
            QPushButton {{
                border: 2px solid {border}; border-radius: 12px;
                background: {background}; color: {text_color}; padding: 8px;
            }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:pressed {{ background: {hover}; border-width: 3px; }}
            QPushButton:focus {{ border: 3px solid {border}; }}
            QPushButton:disabled {{
                border: 2px solid {border}; background: {background}; color: {text_color};
            }}
        """)
        self.updateGeometry()

    def heightForWidth(self, width):
        text_rect = self.fontMetrics().boundingRect(
            QRect(0, 0, max(60, width - 24), 2000),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.text(),
        )
        return max(self.minimumHeight(), text_rect.height() + 24)

    def minimumSizeHint(self):
        return QSize(100, self.minimumHeight())

    def sizeHint(self):
        return QSize(220, self.heightForWidth(220))

    def paintEvent(self, event):
        # QPushButton does not wrap long serial numbers or channel captions itself.
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(
            self.rect().adjusted(12, 10, -12, -10),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.text(),
        )

    def set_interface(self, interface):
        self.device.interface = {"RS232": "RS"}.get(interface.upper(), interface.upper())
        self.set_state(self.device.state)


class DeviceList(QScrollArea):
    def eventFilter(self, watched, event):
        if isinstance(watched, DeviceCard) and event.type() == QEvent.Type.Wheel:
            # Forward wheel events even when the pointer is directly over a button.
            QApplication.sendEvent(self.viewport(), event)
            return True
        return super().eventFilter(watched, event)


class MainMenu(QMainWindow):
    device_requested = pyqtSignal(str)
    exit_requested = pyqtSignal()

    def __init__(self, show_previews=False):
        super().__init__()
        self.exit_allowed = False
        self.setWindowTitle("Измерительная система")
        self.resize(1160, 620)
        self.setMinimumSize(900, 480)
        self.setStyleSheet("""
            QMainWindow, QWidget#menuRoot { background: white; }
            QLabel#categoryTitle {
                color: #00a9df; font-size: 25px; font-weight: 500; border: none;
            }
            QFrame#deviceColumn { border: 2px solid #202020; background: white; }
            QWidget#deviceListContents { background: white; }
            QScrollBar:vertical {
                background: #f2f3f5; width: 12px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #a7adb5; min-height: 32px; border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover { background: #808892; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
            QPushButton#recordAll {
                color: #ee303c; background: white; border: 2px solid #ee303c;
                border-radius: 14px; font-size: 23px; padding: 12px 22px;
            }
            QPushButton#recordAll:hover { background: #fff1f2; }
        """)
        central = QWidget()
        central.setObjectName("menuRoot")
        self.setCentralWidget(central)
        content = QVBoxLayout(central)
        content.setContentsMargins(32, 24, 32, 20)
        content.setSpacing(24)
        columns = QHBoxLayout()
        columns.setSpacing(28)
        self.cards = {}
        self.preview_cards = {}
        self.device_lists = {}
        for device in demo_devices():
            column = QVBoxLayout()
            column.setSpacing(14)
            title = QLabel(device.category)
            title.setObjectName("categoryTitle")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setFixedHeight(76)
            column.addWidget(title)
            panel = DeviceList()
            panel.setObjectName("deviceColumn")
            panel.setWidgetResizable(True)
            panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            panel.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            panel.setAccessibleName(f"Список устройств: {device.category.replace(chr(10), ' ')}")
            list_contents = QWidget()
            list_contents.setObjectName("deviceListContents")
            panel_layout = QVBoxLayout(list_contents)
            panel_layout.setContentsMargins(12, 18, 12, 18)
            panel_layout.setSpacing(14)
            card = DeviceCard(device)
            card.installEventFilter(panel)
            card.clicked.connect(
                lambda checked=False, key=device.key: self.device_requested.emit(key)
            )
            self.cards[device.key] = card
            panel_layout.addWidget(card)
            previews = {
                "multimeter": multimeter_previews,
                "power_supply": power_supply_previews,
            }
            if show_previews and device.key in previews:
                for preview in previews[device.key]():
                    preview_card = DeviceCard(preview)
                    preview_card.installEventFilter(panel)
                    self.preview_cards[preview.key] = preview_card
                    panel_layout.addWidget(preview_card)
            panel_layout.addStretch()
            panel.setWidget(list_contents)
            self.device_lists[device.key] = panel
            column.addWidget(panel, 1)
            columns.addLayout(column, 1)
        content.addLayout(columns, 1)
        self.record_button = QPushButton("Запись логов со всех устройств")
        self.record_button.setObjectName("recordAll")
        self.record_button.setToolTip("Запись логов будет добавлена позже")
        content.addWidget(self.record_button, alignment=Qt.AlignmentFlag.AlignHCenter)

    def update_device(self, device):
        if device.kind == "multimeter" and device.interface == "USB" and not device.present:
            self.remove_device(device.key)
            return
        column = "power_supply" if device.kind == "power_supply" else "multimeter"
        panel = self.device_lists[column]
        layout = panel.widget().layout()
        card = self.cards.get(device.key)
        if card is None:
            card = DeviceCard(device)
            card.clicked.connect(
                lambda checked=False, key=device.key: self.device_requested.emit(key)
            )
            self.cards[device.key] = card
        old_panel = getattr(card, "_panel", None)
        if old_panel is not panel:
            if old_panel is not None:
                old_panel.widget().layout().removeWidget(card)
                card.removeEventFilter(old_panel)
            layout.insertWidget(layout.count() - 1, card)
            card.installEventFilter(panel)
            card._panel = panel
        card.device = device
        card.setMinimumHeight(110 if device.channel_values else 76)
        card.set_state(device.state)
        if not device.present or device.reachable is False:
            card.setToolTip("Устройство не подключено")
        elif device.resource:
            card.setToolTip(f"{device.state.value}\n{device.resource}\n{device.identity}")
        card.show()

    def remove_device(self, key):
        card = self.cards.pop(key, None)
        if card is not None:
            card._panel.widget().layout().removeWidget(card)
            card.hide()
            card.deleteLater()

    def closeEvent(self, event):
        if self.exit_allowed:
            event.accept()
        else:
            event.ignore()
            self.exit_requested.emit()
