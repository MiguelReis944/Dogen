"""Application settings dialog — reads/writes settings.json."""

import json
from pathlib import Path

from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                              QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
                              QLabel, QSpinBox, QToolButton, QToolTip, QVBoxLayout,
                              QWidget)

from utils.config import AppConfig, save_config
from ui.dogen_logo import add_dialog_header


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, settings_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)
        self.config = config
        self.settings_path = settings_path

        outer = QVBoxLayout(self)
        outer.setSpacing(10)
        add_dialog_header(self, outer, "Settings")

        # ── Speech Recognition ─────────────────────────────────────────────────
        stt_box = QGroupBox("Speech Recognition (Whisper)")
        form1 = QFormLayout(stt_box)
        self._whisper = QComboBox()
        for m in ["tiny.en", "base.en", "small.en", "medium.en", "large"]:
            self._whisper.addItem(m)
        idx = self._whisper.findText(config.whisper_model)
        self._whisper.setCurrentIndex(max(idx, 0))
        form1.addRow(
            self._label_with_help(
                "Model:",
                "Chooses the local Whisper speech-recognition model. Larger models can be more accurate, but use more memory and take longer. The .en models are intended for English speech.",
            ),
            self._whisper,
        )

        self._review = QCheckBox("Review transcript before sending")
        self._review.setObjectName("transcriptReviewCheck")
        self._review.setChecked(config.review_transcript)
        self._review.setToolTip(
            "When enabled, you can read and edit Whisper's transcript before it is sent to the coach."
        )
        form1.addRow(self._option_with_help(
            self._review,
            "Shows the recognized words for review before the coach receives them. This helps catch transcription mistakes.",
        ))

        self._review_auto_send = QComboBox()
        self._review_auto_send.setObjectName("transcriptReviewAutoSendDelay")
        for label, seconds in [
            ("10 seconds", 10),
            ("15 seconds", 15),
            ("30 seconds", 30),
            ("Never", None),
        ]:
            self._review_auto_send.addItem(label, seconds)
        delay_index = self._review_auto_send.findData(
            config.review_transcript_auto_send_seconds
        )
        self._review_auto_send.setCurrentIndex(
            delay_index if delay_index >= 0 else self._review_auto_send.findData(15)
        )
        self._review_auto_send.setToolTip(
            "How long the transcript stays open before it is sent automatically. Choose Never to wait for your confirmation."
        )
        form1.addRow(
            self._label_with_help(
                "Send automatically after:",
                "Sets the review countdown. After the selected delay, the current transcript is sent automatically; Never requires you to confirm it yourself.",
            ),
            self._review_auto_send,
        )
        self._review_auto_send.setEnabled(config.review_transcript)
        self._review.toggled.connect(self._review_auto_send.setEnabled)

        self._noise_reduction = QCheckBox("Reduce background noise after recording")
        self._noise_reduction.setObjectName("noiseReductionCheck")
        self._noise_reduction.setChecked(config.noise_reduction)
        self._noise_reduction.setToolTip(
            "Applies local noise reduction after recording and before transcription."
        )
        form1.addRow(self._option_with_help(
            self._noise_reduction,
            "Attempts to reduce steady background noise after the recording ends. This can help recognition in noisy rooms, but may alter the sound; turn it off to compare.",
        ))
        outer.addWidget(stt_box)

        # ── Recording ──────────────────────────────────────────────────────────
        vad_box = QGroupBox("Recording")
        form2 = QFormLayout(vad_box)
        self._threshold = QDoubleSpinBox()
        self._threshold.setRange(0.001, 0.1)
        self._threshold.setSingleStep(0.001)
        self._threshold.setDecimals(3)
        self._threshold.setValue(config.vad_threshold)
        self._threshold.setToolTip(
            "Voice-activity detection threshold. The current click-to-record mode does not use it to end a recording."
        )
        form2.addRow(
            self._label_with_help(
                "Mic sensitivity:",
                "Sets the voice-activity detection threshold. The current recording control is manual, so this setting does not change the volume animation or stop a push-to-talk recording.",
            ),
            self._threshold,
        )

        form2.addRow(
            self._label_with_help(
                "Recording control:",
                "Click Start recording once to begin, then click Finish recording to send the captured audio. You do not need to hold the button.",
            ),
            QLabel("Click once to start, once to finish"),
        )
        form2.addRow(
            self._label_with_help(
                "Recording time limit:",
                "A single recording currently ends after 60 seconds. Longer thoughts can be sent as multiple turns.",
            ),
            QLabel("Up to 60 seconds per turn"),
        )
        outer.addWidget(vad_box)

        # ── Conversation ───────────────────────────────────────────────────────
        ctx_box = QGroupBox("Conversation")
        form3 = QFormLayout(ctx_box)
        self._context_size = QSpinBox()
        self._context_size.setRange(4, 100)
        self._context_size.setValue(config.context_size)
        self._context_size.setToolTip(
            "Controls how many recent user-and-coach turn pairs are sent to Ollama."
        )
        form3.addRow(
            self._label_with_help(
                "Context turns kept:",
                "Sets how many recent user-and-coach turn pairs the local Ollama model receives for continuity. More context can improve follow-up answers, but uses more of the model's context window. Older conversation remains in the chat history.",
            ),
            self._context_size,
        )
        outer.addWidget(ctx_box)

        # ── privacy ────────────────────────────────────────────────────────────
        privacy_box = QGroupBox("Privacy")
        privacy_layout = QVBoxLayout(privacy_box)
        self._diagnostics = QCheckBox(
            "Save local reliability diagnostics (no audio or transcripts)"
        )
        self._diagnostics.setObjectName("localDiagnosticsCheck")
        self._diagnostics.setChecked(config.diagnostics_enabled)
        self._diagnostics.setToolTip(
            "Stores allowlisted reliability metadata on this computer only. "
            "Turning this off stops new diagnostic log entries immediately."
        )
        privacy_layout.addWidget(self._option_with_help(
            self._diagnostics,
            "Stores allowlisted reliability details on this computer only, such as stage durations and failure types. It never stores audio or conversation text. Turning this off stops new entries immediately.",
        ))
        outer.addWidget(privacy_box)

        # ── daily practice goal ────────────────────────────────────────────────
        goal_box = QGroupBox("Today")
        goal_form = QFormLayout(goal_box)
        self._daily_goal = QSpinBox()
        self._daily_goal.setObjectName("dailyRecordingGoalMinutes")
        self._daily_goal.setRange(1, 180)
        self._daily_goal.setSuffix(" min")
        self._daily_goal.setValue(config.daily_recording_goal_minutes)
        self._daily_goal.setToolTip(
            "Daily target based on audio frames captured while recording. Processing and pauses are not counted."
        )
        goal_form.addRow(
            self._label_with_help(
                "Recording goal:",
                "Sets the daily audio-recording target shown in Today. Only captured audio time counts; processing and time between recordings do not.",
            ),
            self._daily_goal,
        )
        outer.addWidget(goal_box)

        # ── practice text size ─────────────────────────────────────────────────
        text_box = QGroupBox("Appearance")
        text_form = QFormLayout(text_box)
        self._font_size = QSpinBox()
        self._font_size.setObjectName("practiceFontSizePx")
        self._font_size.setRange(12, 24)
        self._font_size.setSuffix(" px")
        self._font_size.setValue(config.practice_font_size_px)
        self._font_size.setToolTip(
            "Changes text size in Conversation, Today, and Fixes."
        )
        text_form.addRow(
            self._label_with_help(
                "Practice text size:",
                "Changes the reading size in Conversation, Today, and Fixes. It does not change text in other windows.",
            ),
            self._font_size,
        )
        outer.addWidget(text_box)

        # ── Buttons ────────────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

    def _save(self):
        self.config.whisper_model       = self._whisper.currentText()
        self.config.review_transcript   = self._review.isChecked()
        self.config.review_transcript_auto_send_seconds = (
            self._review_auto_send.currentData()
        )
        self.config.noise_reduction     = self._noise_reduction.isChecked()
        self.config.diagnostics_enabled = self._diagnostics.isChecked()
        self.config.vad_threshold       = self._threshold.value()
        self.config.input_mode          = "ptt"
        self.config.context_size        = self._context_size.value()
        self.config.daily_recording_goal_minutes = self._daily_goal.value()
        self.config.practice_font_size_px   = self._font_size.value()
        save_config(self.config, self.settings_path)
        self.accept()

    @staticmethod
    def _help_button(text: str) -> QToolButton:
        button = QToolButton()
        button.setText("?")
        button.setAutoRaise(True)
        button.setFixedSize(18, 18)
        button.setAccessibleName(f"Help: {text}")
        button.setToolTip(text)
        button.setWhatsThis(text)
        button.clicked.connect(
            lambda _checked=False, help_button=button, message=text: QToolTip.showText(
                help_button.mapToGlobal(help_button.rect().bottomLeft()),
                message,
                help_button,
            )
        )
        button.setStyleSheet(
            "QToolButton { border: 1px solid #617080; border-radius: 9px; "
            "color: #b7c3d0; font-weight: bold; padding: 0; }"
            "QToolButton:hover { color: #ffffff; border-color: #49d98a; }"
        )
        return button

    @classmethod
    def _label_with_help(cls, label: str, help_text: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(QLabel(label))
        layout.addWidget(cls._help_button(help_text))
        layout.addStretch(1)
        return row

    @classmethod
    def _option_with_help(cls, option: QCheckBox, help_text: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(option)
        layout.addWidget(cls._help_button(help_text))
        layout.addStretch(1)
        return row
