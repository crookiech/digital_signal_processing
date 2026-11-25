import os
from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase


def configure_font(app):
    # Explicit registration also supports Qt's offscreen renderer on Windows.
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
    if font_path.is_file():
        QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Segoe UI", 11))
