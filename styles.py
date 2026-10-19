GLOBAL_QSS = """
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 16px;
    subcontrol-origin: border;
}

QDoubleSpinBox::up-button {
    subcontrol-position: top right;
}

QDoubleSpinBox::down-button {
    subcontrol-position: bottom right;
}

QGroupBox {
    font-weight: bold;
    border: 1px solid #c0c0c0;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
}

QPushButton {
    padding: 6px 16px;
    min-height: 22px;
    background-color: #f0f0f0;
    border: 1px solid #c0c0c0;
    border-radius: 4px;
    color: #000000;
}

QPushButton:hover {
    background-color: #e0e0e0;
}

QComboBox, QDoubleSpinBox {
    padding: 4px 6px;
    min-height: 22px;
}

QPlainTextEdit {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
}
"""

CHANNEL_STYLE_TEMPLATE = """
QGroupBox {{
    border: 2px solid {border};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
    color: {border};
}}
"""

STATUS_STYLE_TEMPLATE = """
QLabel {{
    color: {color};
    background-color: {bg};
    border: 2px solid {border};
    border-radius: 6px;
    padding: 4px 12px;
    font-weight: bold;
}}
"""

CHANNEL_COLORS = {
    "green": "#1b5e20",
    "blue":  "#1565c0",
}

STATUS_COLORS = {
    "disconnected": {
        "text": "Отключено",
        "color": "#b71c1c", "bg": "#ffebee", "border": "#ef5350",
    },
    "connected": {
        "text": "Подключено",
        "color": "#1b5e20", "bg": "#e8f5e9", "border": "#66bb6a",
    },
}