"""Dialog that shows all corrections collected during practice sessions."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel,
                              QPushButton, QTableWidget, QTableWidgetItem,
                              QVBoxLayout)
from ui.dogen_logo import add_dialog_header


class VocabDialog(QDialog):
    def __init__(self, vocab_items, on_clear, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vocabulary Tracker")
        self.resize(640, 420)
        self._on_clear = on_clear

        layout = QVBoxLayout(self)
        add_dialog_header(self, layout, "Vocabulary")

        if not vocab_items:
            layout.addWidget(QLabel("No corrections recorded yet. Keep practicing!"))
        else:
            self._table = QTableWidget(len(vocab_items), 3)
            self._table.setHorizontalHeaderLabels(["You said", "Correct form", "When"])
            self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            self._table.setEditTriggers(QTableWidget.NoEditTriggers)
            self._table.setAlternatingRowColors(True)
            for i, item in enumerate(vocab_items):
                self._table.setItem(i, 0, QTableWidgetItem(item.original))
                self._table.setItem(i, 1, QTableWidgetItem(item.corrected))
                date = item.created_at[:10] if item.created_at else ""
                self._table.setItem(i, 2, QTableWidgetItem(date))
            layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Clear history")
        clear_btn.clicked.connect(self._clear)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _clear(self):
        self._on_clear()
        self.accept()
