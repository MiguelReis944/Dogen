"""End-of-session summary dialog."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QGroupBox,
                              QHBoxLayout, QLabel, QTableWidget,
                              QTableWidgetItem, QVBoxLayout)
from ui.dogen_logo import add_dialog_header


class SessionSummaryDialog(QDialog):
    NEW_SESSION = 1
    CONTINUE    = 0

    def __init__(self, stats: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Session Summary")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        add_dialog_header(self, layout, "Session summary")

        turns       = stats.get("turns", 0)
        corrections = stats.get("corrections", 0)
        fillers     = stats.get("fillers", 0)
        minutes     = stats.get("minutes", 0.0)

        # ── headline numbers ───────────────────────────────────────────────────
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(24)
        for value, label in [
            (str(turns),       "turns"),
            (f"{minutes:.1f}", "recorded min"),
            (str(corrections), "corrections"),
            (str(fillers),     "filler words"),
        ]:
            box = QVBoxLayout()
            v = QLabel(value)
            v.setStyleSheet("font-size: 28px; font-weight: bold;")
            v.setAlignment(Qt.AlignCenter)
            l = QLabel(label)
            l.setStyleSheet("color: #888; font-size: 12px;")
            l.setAlignment(Qt.AlignCenter)
            box.addWidget(v)
            box.addWidget(l)
            metrics_row.addLayout(box)
        layout.addLayout(metrics_row)

        # ── corrections table ──────────────────────────────────────────────────
        vocab = stats.get("vocab", [])
        if vocab:
            grp = QGroupBox("Corrections this session")
            grp_layout = QVBoxLayout(grp)
            table = QTableWidget(len(vocab), 2)
            table.setHorizontalHeaderLabels(["You said", "Correct form"])
            table.horizontalHeader().setStretchLastSection(True)
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setMaximumHeight(160)
            for i, item in enumerate(vocab):
                table.setItem(i, 0, QTableWidgetItem(item.original))
                table.setItem(i, 1, QTableWidgetItem(item.corrected))
            grp_layout.addWidget(table)
            layout.addWidget(grp)

        # ── buttons ────────────────────────────────────────────────────────────
        btns = QHBoxLayout()
        from PyQt5.QtWidgets import QPushButton
        new_btn  = QPushButton("New Session")
        cont_btn = QPushButton("Continue")
        cont_btn.setDefault(True)
        btns.addWidget(new_btn)
        btns.addWidget(cont_btn)
        layout.addLayout(btns)

        new_btn.clicked.connect(lambda: self.done(self.NEW_SESSION))
        cont_btn.clicked.connect(lambda: self.done(self.CONTINUE))
