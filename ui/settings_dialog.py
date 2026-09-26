"""Application settings dialog — reads/writes settings.json."""

import json
from pathlib import Path

from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                              QDoubleSpinBox, QFormLayout, QGroupBox, QSpinBox,
                              QVBoxLayout)

from utils.config import AppConfig, save_config


PAUSE_PRESETS = {
    "Short": 1.2,
    "Normal": 2.0,
    "Long": 3.0,
}


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
        self._review.setObjectName("transcriptReviewCheck")
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

        self._input_mode = QComboBox()
        self._input_mode.setObjectName("inputModeCombo")
        self._input_mode.addItem("Push-to-talk", "ptt")
        self._input_mode.addItem("Automatic", "vad")
        self._input_mode.setCurrentIndex(max(self._input_mode.findData(config.input_mode), 0))
        form2.addRow("Input mode:", self._input_mode)

        self._pause_preset = QComboBox()
        self._pause_preset.setObjectName("pausePresetCombo")
        for label, seconds in PAUSE_PRESETS.items():
            self._pause_preset.addItem(label, seconds)
        self._pause_preset.addItem("Custom", None)
        form2.addRow("Automatic pause:", self._pause_preset)

        self._silence = QDoubleSpinBox()
        self._silence.setRange(0.3, 5.0)
        self._silence.setSingleStep(0.1)
        self._silence.setDecimals(1)
        self._silence.setValue(config.silence_duration_sec)
        form2.addRow("Custom pause (s):", self._silence)
        self._pause_preset.currentIndexChanged.connect(self._apply_pause_preset)
        self._silence.valueChanged.connect(self._sync_pause_preset)
        self._sync_pause_preset(config.silence_duration_sec)
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
        self.config.input_mode          = self._input_mode.currentData()
        self.config.context_size        = self._context_size.value()
        save_config(self.config, self.settings_path)
        self.accept()

    def _apply_pause_preset(self, index):
        seconds = self._pause_preset.itemData(index)
        if seconds is not None:
            self._silence.setValue(float(seconds))

    def _sync_pause_preset(self, seconds):
        index = self._pause_preset.findText("Custom")
        for label, preset_seconds in PAUSE_PRESETS.items():
            if abs(float(seconds) - preset_seconds) < 0.001:
                index = self._pause_preset.findText(label)
                break
        self._pause_preset.blockSignals(True)
        self._pause_preset.setCurrentIndex(index)
        self._pause_preset.blockSignals(False)
