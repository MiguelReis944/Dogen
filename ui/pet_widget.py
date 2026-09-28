"""Dogen's visual body — a small pixel-style face reacting to conversation state."""

import math
import random

from PyQt5.QtCore import QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QWidget

_ACCENT = QColor("#4ade80")
_ACCENT_DIM = QColor("#1f6b46")
_BG = QColor("#0a0e14")
_BORDER = QColor("#1f2a37")


def _wave(x: float) -> float:
    return math.sin(x * math.pi)


class PetWidget(QWidget):
    """States: idle | listening | thinking | speaking."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self._state = "idle"
        self._phase = 0.0
        self._blink = 0.0
        self._next_blink_at = random.uniform(2.0, 5.0)
        self._volume = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def set_state(self, state: str):
        if state != self._state:
            self._state = state
            self._phase = 0.0

    def set_volume(self, rms: float):
        self._volume = max(0.0, min(1.0, rms * 8))

    @property
    def visual_volume(self) -> float:
        return self._volume

    def _tick(self):
        self._phase += 0.05
        if self._state == "idle":
            self._next_blink_at -= 0.05
            if self._next_blink_at <= 0:
                self._blink = 1.0
                self._next_blink_at = random.uniform(2.5, 6.0)
            elif self._blink > 0:
                self._blink = max(0.0, self._blink - 0.25)
        else:
            self._blink = 0.0
            if self._state == "speaking":
                # Decay toward closed between playback volume updates so the
                # mouth doesn't freeze open during gaps (sentence boundaries).
                self._volume *= 0.85
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        panel = QRectF(4, 4, w - 8, h - 8)
        p.setPen(QPen(_BORDER, 2))
        p.setBrush(_BG)
        p.drawRoundedRect(panel, 10, 10)

        cx, cy = w / 2, h / 2 - 8
        eye_w, eye_h = 46, 46
        gap = 30

        if self._state == "listening":
            eye_h *= 1.0 + 0.35 * self._volume
        elif self._state == "thinking":
            eye_h *= 0.55 + 0.15 * abs(_wave(self._phase * 2))

        open_ratio = max(0.08, 1.0 - self._blink)
        drawn_h = eye_h * open_ratio

        left_rect = QRectF(cx - gap - eye_w, cy - drawn_h / 2, eye_w, drawn_h)
        right_rect = QRectF(cx + gap, cy - drawn_h / 2, eye_w, drawn_h)

        p.setPen(Qt.NoPen)
        p.setBrush(_ACCENT)
        p.drawRoundedRect(left_rect, 10, 10)
        p.drawRoundedRect(right_rect, 10, 10)

        if self._state == "thinking":
            for i in range(3):
                dot_phase = (self._phase * 3 - i * 0.6) % 3
                alpha = int(255 * max(0.15, 1 - abs(dot_phase - 1)))
                color = QColor(_ACCENT)
                color.setAlpha(alpha)
                p.setBrush(color)
                p.drawEllipse(QRectF(cx - 24 + i * 22, cy + 46, 10, 10))
        else:
            mouth_w = 70
            mouth_h = 6
            if self._state == "speaking":
                # Driven by actual TTS playback amplitude (set_volume), with a
                # light wobble on top so it doesn't look static mid-syllable.
                base = 6 + 44 * self._volume
                wobble = 4 * abs(_wave(self._phase * 6))
                mouth_h = max(6, min(30, base + wobble))
            mouth_rect = QRectF(cx - mouth_w / 2, cy + 42, mouth_w, mouth_h)
            p.setBrush(_ACCENT_DIM if self._state == "idle" else _ACCENT)
            p.drawRoundedRect(mouth_rect, 4, 4)

        p.end()
