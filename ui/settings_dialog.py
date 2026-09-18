"""Application settings dialog — reads/writes settings.json."""

import json
from pathlib import Path

from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                              QDoubleSpinBox, QFormLayout, QGroupBox, QSpinBox,
                              QVBoxLayout)

from utils.config import AppConfig, save_config


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, settings_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)
        self.config = config
        self.settings_path = settings_path

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        # ── Speech Recognition ─────────────────────────────────────────────────
        stt_box = QGroupBox("Speech Recognition (Whisper)")
        form1 = QFormLayout(stt_box)
        self._whisper = QComboBox()
        for m in ["tiny.en", "base.en", "small.en", "medium.en", "large"]:
            self._whisper.addItem(m)
        idx = self._whisper.findText(config.whisper_model)
        self._whisper.setCurrentIndex(max(idx, 0))
        form1.addRow("Model:", self._whisper)

        self._review = QCheckBox("Review transcript before sending")
        self._review.setChecked(config.review_transcript)
        form1.addRow("", self._review)
        outer.addWidget(stt_box)

        # ── Voice Detection ────────────────────────────────────────────────────
        vad_box = QGroupBox("Voice Detection")
        form2 = QFormLayout(vad_box)
        self._threshold = QDoubleSpinBox()
        self._threshold.setRange(0.001, 0.1)
        self._threshold.setSingleStep(0.001)
        self._threshold.setDecimals(3)
        self._threshold.setValue(config.vad_threshold)
        form2.addRow("Mic sensitivity:", self._threshold)

        self._silence = QDoubleSpinBox()
        self._silence.setRange(0.3, 5.0)
        self._silence.setSingleStep(0.1)
        self._silence.setDecimals(1)
        self._silence.setValue(config.silence_duration_sec)
        form2.addRow("Silence before stop (s):", self._silence)

        self._input_mode = QComboBox()
        self._input_mode.addItems(["vad", "ptt"])
        self._input_mode.setCurrentText(config.input_mode)
        form2.addRow("Input mode:", self._input_mode)
        outer.addWidget(vad_box)

        # ── Conversation ───────────────────────────────────────────────────────
        ctx_box = QGroupBox("Conversation")
        form3 = QFormLayout(ctx_box)
        self._context_size = QSpinBox()
        self._context_size.setRange(4, 100)
        self._context_size.setValue(config.context_size)
        form3.addRow("Context turns kept:", self._context_size)
        outer.addWidget(ctx_box)

        # ── Buttons ────────────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

    def _save(self):
        self.config.whisper_model       = self._whisper.currentText()
        self.config.review_transcript   = self._review.isChecked()
        self.config.vad_threshold       = self._threshold.value()
        self.config.silence_duration_sec = self._silence.value()
        self.config.input_mode          = self._input_mode.currentText()
        self.config.context_size        = self._context_size.value()
        save_config(self.config, self.settings_path)
        self.accept()
