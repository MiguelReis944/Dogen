"""Reusable Dogen face and dialog header."""

from pathlib import Path

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QPainter, QPalette
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QWidget


class DogenLogo(QWidget):
    """The face from the conversation HUD, without its surrounding panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scale = 1.0
        self.setScale(1.0)

    def setScale(self, scale: float):
        if scale <= 0:
            raise ValueError("Logo scale must be positive")
        self._scale = float(scale)
        self.setFixedSize(self.sizeHint())
        self.update()

    def sizeHint(self):
        return QSize(round(110 * self._scale), round(68 * self._scale))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(self.width() / 110, self.height() / 68)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#4ade80"))
        painter.drawRoundedRect(4, 4, 36, 36, 8, 8)
        painter.drawRoundedRect(70, 4, 36, 36, 8, 8)
        painter.setBrush(QColor("#1f6b46"))
        painter.drawRoundedRect(28, 58, 54, 6, 3, 3)
        painter.end()


def add_dialog_header(dialog, layout, title: str):
    """Apply the HUD surface and add a compact branded title row."""
    palette = dialog.palette()
    palette.setColor(QPalette.Window, QColor("#0a0e14"))
    palette.setColor(QPalette.WindowText, QColor("#d7ffe4"))
    dialog.setPalette(palette)
    dialog.setAutoFillBackground(True)
    dialog.setStyleSheet(Path(__file__).with_name("styles.qss").read_text(encoding="utf-8"))

    header = QHBoxLayout()
    logo = DogenLogo(dialog)
    logo.setScale(0.65)
    header.addWidget(logo)
    label = QLabel(title)
    label.setObjectName("dialogTitle")
    header.addWidget(label)
    header.addStretch()
    layout.addLayout(header)
    return logo
