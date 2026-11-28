from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QGroupBox, QFormLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QPushButton, QComboBox, QRadioButton, QButtonGroup)
from .styles import (CHANNEL_COLORS, CHANNEL_STYLE_TEMPLATE, OPERATING_MODES, CH3_VOLTAGES)

class ChannelPanel(QGroupBox):
    set_v_requested = pyqtSignal(int, float)
    set_i_requested = pyqtSignal(int, float)
    mode_changed = pyqtSignal(int, str)

    def __init__(self, ch: int, accent_key="green", mode_key: str = "arm"):
        super().__init__(f"CH{ch}")
        self.ch = ch
        self._accent_key = accent_key
        self._mode_key = mode_key

        layout = QFormLayout()
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(10)

        self.v_spin = QDoubleSpinBox()
        self.v_spin.setValue(0)
        self.v_spin.setDecimals(2)
        self.v_spin.setSingleStep(0.01)
        self.v_spin.setSuffix(" В")
        self.v_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)

        self.i_spin = QDoubleSpinBox()
        self.i_spin.setValue(0)
        self.i_spin.setDecimals(3)
        self.i_spin.setSingleStep(0.001)
        self.i_spin.setSuffix(" А")

        btn_v = QPushButton("Установить")
        btn_i = QPushButton("Установить")
        btn_v.clicked.connect(lambda: self.set_v_requested.emit(self.ch, self.v_spin.value()))
        btn_i.clicked.connect(lambda: self.set_i_requested.emit(self.ch, self.i_spin.value()))

        row_v = QHBoxLayout()
        row_v.addWidget(self.v_spin, 1)
        row_v.addWidget(btn_v)
        row_v.setSpacing(8)

        row_i = QHBoxLayout()
        row_i.addWidget(self.i_spin, 1)
        row_i.addWidget(btn_i)
        row_i.setSpacing(8)

        self.lbl_v = QLabel("Напряжение:")
        self.lbl_v.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_v.setWordWrap(True)

        self.lbl_i = QLabel("Ток:")
        self.lbl_i.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_i.setWordWrap(True)

        layout.addRow(self.lbl_v, row_v)
        layout.addRow(self.lbl_i, row_i)
        self.confirmed_label = QLabel("Прибор: —")
        self.confirmed_label.setWordWrap(True)
        layout.addRow(self.confirmed_label)

        self.range_group = QButtonGroup(self)
        self.range_group.setExclusive(True)
        range_row = QHBoxLayout()
        range_row.setSpacing(10)
        for key, cfg in OPERATING_MODES.items():
            rb = QRadioButton(cfg["label"])
            rb.setProperty("mode_key", key)
            rb.setToolTip(f"{cfg['v_min']}-{cfg['v_max']} В, {cfg['i_min']}-{cfg['i_max']} А")
            if key == mode_key:
                rb.setChecked(True)
            self.range_group.addButton(rb)
            range_row.addWidget(rb)
        range_row.addStretch(1)

        range_lbl = QLabel("Режим:")
        range_lbl.setTextFormat(Qt.TextFormat.RichText)

        layout.addRow(range_lbl, range_row)

        self.setLayout(layout)
        self.setStyleSheet(CHANNEL_STYLE_TEMPLATE.format(border=CHANNEL_COLORS[accent_key]))

        self._apply_mode(mode_key)
        self.range_group.buttonClicked.connect(self._on_radio_clicked)

    def show_confirmed(self, voltage, current, initialize=False):
        self.confirmed_label.setText(
            f"Прибор: {voltage:.2f} В / {current:.3f} А"
        )
        if initialize:
            # Do not silently clamp an existing instrument setting to ARM limits.
            if not (self.v_spin.minimum() <= voltage <= self.v_spin.maximum()
                    and self.i_spin.minimum() <= current <= self.i_spin.maximum()):
                self._mode_key = "free"
                for button in self.range_group.buttons():
                    button.setChecked(button.property("mode_key") == "free")
                self._apply_mode("free")
            self.v_spin.setValue(voltage)
            self.i_spin.setValue(current)

    def _on_radio_clicked(self, btn: QRadioButton):
        key = btn.property("mode_key")
        if key and key != self._mode_key:
            self._mode_key = key
            self._apply_mode(key)
            self.mode_changed.emit(self.ch, key)

    def _apply_mode(self, key: str):
        cfg = OPERATING_MODES[key]
        self.apply_range(cfg["v_min"], cfg["v_max"], cfg["i_min"], cfg["i_max"])

    def apply_range(self, v_min, v_max, i_min, i_max):
        self.v_spin.setRange(v_min, v_max)
        self.i_spin.setRange(i_min, i_max)
        self.lbl_v.setText(f'Напряжение:<br><span style="color:#808080">{v_min}-{v_max} В</span>')
        self.lbl_i.setText(f'Ток:<br><span style="color:#808080">{i_min}-{i_max} А</span>')


class ChannelPanel3(QGroupBox):
    set_v_requested = pyqtSignal(int, float)
    set_i_requested = pyqtSignal(int, float)

    def __init__(self, ch: int = 3, i_min: float = 0.0, i_max: float = 3.0,accent_key: str = "orange"):
        super().__init__(f"CH{ch}")
        self.ch = ch
        self._accent_key = accent_key

        layout = QFormLayout()
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(10)

        self.v_combo = QComboBox()
        for v in CH3_VOLTAGES:
            self.v_combo.addItem(f"{v:.1f} В", v)
        self.v_combo.setCurrentIndex(0)

        self.i_spin = QDoubleSpinBox()
        self.i_spin.setRange(i_min, i_max)
        self.i_spin.setValue(0)
        self.i_spin.setDecimals(3)
        self.i_spin.setSingleStep(0.001)
        self.i_spin.setSuffix(" А")

        btn_v = QPushButton("Установить")
        btn_i = QPushButton("Установить")
        btn_v.clicked.connect(lambda: self.set_v_requested.emit(self.ch, float(self.v_combo.currentData())))
        btn_i.clicked.connect(lambda: self.set_i_requested.emit(self.ch, self.i_spin.value()))

        row_v = QHBoxLayout()
        row_v.addWidget(self.v_combo, 1)
        row_v.addWidget(btn_v)
        row_v.setSpacing(8)

        row_i = QHBoxLayout()
        row_i.addWidget(self.i_spin, 1)
        row_i.addWidget(btn_i)
        row_i.setSpacing(8)

        lbl_v = QLabel('Напряжение:<br><span style="color:#808080">1.8/2.5/3.3/5.0 В</span>')
        lbl_v.setTextFormat(Qt.TextFormat.RichText)
        lbl_v.setWordWrap(True)

        lbl_i = QLabel(f'Ток:<br><span style="color:#808080">{i_min}-{i_max} А</span>')
        lbl_i.setTextFormat(Qt.TextFormat.RichText)
        lbl_i.setWordWrap(True)

        layout.addRow(lbl_v, row_v)
        layout.addRow(lbl_i, row_i)
        self.confirmed_label = QLabel("Прибор: —")
        self.confirmed_label.setWordWrap(True)
        layout.addRow(self.confirmed_label)
        self.setLayout(layout)

        self.setStyleSheet(CHANNEL_STYLE_TEMPLATE.format(border=CHANNEL_COLORS[accent_key]))

    def show_confirmed(self, voltage, current, initialize=False):
        self.confirmed_label.setText(
            f"Прибор: {voltage:.2f} В / {current:.3f} А"
        )
        if initialize:
            self.set_voltage_display(voltage)
            self.i_spin.setValue(current)

    def set_voltage_display(self, value: float):
        nearest = min(CH3_VOLTAGES, key=lambda x: abs(x - value))
        idx = CH3_VOLTAGES.index(nearest)
        self.v_combo.setCurrentIndex(idx)