"""Block energy detector for end-of-utterance decisions."""

import numpy as np


class VoiceDetector:
    def __init__(self, threshold: float, silence_duration_sec: float, sample_rate: int):
        self.threshold = threshold
        self.silence_duration_sec = silence_duration_sec
        self.sample_rate = sample_rate
        self.heard_voice = False
        self.silent_samples = 0

    def feed(self, samples) -> bool:
        block = np.asarray(samples, dtype=np.float32)
        rms = float(np.sqrt(np.mean(block ** 2))) if block.size else 0.0
        if rms >= self.threshold:
            self.heard_voice = True
            self.silent_samples = 0
        elif self.heard_voice:
            self.silent_samples += block.size
        return self.heard_voice and self.silent_samples >= self.silence_duration_sec * self.sample_rate
