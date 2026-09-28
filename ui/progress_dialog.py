"""Local, evidence-based practice progress."""

from datetime import date

from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from ui.dogen_logo import add_dialog_header


class ProgressDialog(QDialog):
    def __init__(self, progress_service, today=None, parent=None):
        super().__init__(parent)
        self.progress_service = progress_service
        self.today = today or date.today()
        self.setWindowTitle("Practice progress")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        add_dialog_header(self, layout, "Practice progress")
        self.period_combo = QComboBox()
        self.period_combo.addItem("Last 7 days", 7)
        self.period_combo.addItem("Last 30 days", 30)
        self.period_combo.currentIndexChanged.connect(self._refresh)
        layout.addWidget(self.period_combo)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        form = QFormLayout()
        self.streak_label = QLabel()
        self.days_label = QLabel()
        self.practice_label = QLabel()
        self.turns_label = QLabel()
        self.words_label = QLabel()
        self.fillers_label = QLabel()
        self.edits_label = QLabel()
        self.vocabulary_label = QLabel()
        self.edits_label.setToolTip(
            "Transcripts you changed before sending. This measures recognition reliability, "
            "not language proficiency."
        )
        form.addRow("Current streak:", self.streak_label)
        form.addRow("Practice days:", self.days_label)
        form.addRow("Practice time:", self.practice_label)
        form.addRow("Completed turns:", self.turns_label)
        form.addRow("Words spoken:", self.words_label)
        form.addRow("Fillers / 100 words:", self.fillers_label)
        form.addRow("Transcripts you edited:", self.edits_label)
        form.addRow("Vocabulary encountered:", self.vocabulary_label)
        layout.addLayout(form)

        self.category_table = QTableWidget(0, 2)
        self.category_table.setHorizontalHeaderLabels(["Correction category", "Count"])
        self.category_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.category_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        layout.addWidget(self.category_table)

        note = QLabel(
            "These are local activity and correction metrics, not a standardized "
            "pronunciation, fluency, or proficiency score."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(note)
        self._refresh()

    def _refresh(self):
        stats = self.progress_service.stats(self.period_combo.currentData(), self.today)
        if stats.completed_turns == 0:
            self.status_label.setText("Complete your first conversation to see progress")
        elif stats.practiced_days < 3:
            self.status_label.setText("More practice days are needed for a trend")
        else:
            self.status_label.setText("Your recent practice activity")

        self.streak_label.setText(f"{stats.current_streak} days")
        self.days_label.setText(str(stats.practiced_days))
        self.practice_label.setText(f"{stats.minutes_practiced:.1f} minutes")
        self.turns_label.setText(str(stats.completed_turns))
        self.words_label.setText(str(stats.words_spoken))
        self.fillers_label.setText(
            "Not enough data"
            if stats.fillers_per_100_words is None
            else f"{stats.fillers_per_100_words:.1f}"
        )
        self.edits_label.setText(
            "Not enough data"
            if stats.transcript_edit_rate is None
            else f"{stats.transcript_edit_rate * 100:.1f}%"
        )
        self.vocabulary_label.setText(str(stats.vocabulary_count))

        categories = sorted(stats.corrections_by_category.items())
        self.category_table.setRowCount(len(categories))
        for row, (category, count) in enumerate(categories):
            self.category_table.setItem(row, 0, QTableWidgetItem(category.replace("_", " ")))
            self.category_table.setItem(row, 1, QTableWidgetItem(str(count)))
