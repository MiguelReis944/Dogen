"""Block energy detector for end-of-utterance decisions."""

import numpy as np


class VoiceDetector:
    # ponytail: adaptive noise floor via EMA; upgrade to webrtcvad if false-positives persist in noisy environments
    _ALPHA = 0.05  # smoothing factor for background noise estimate

    def __init__(self, threshold: float, silence_duration_sec: float, sample_rate: int):
        self.base_threshold = threshold
        self.silence_duration_sec = silence_duration_sec
        self.sample_rate = sample_rate
        self.heard_voice = False
        self.silent_samples = 0
        self._noise_floor = 0.0

    def feed(self, samples) -> bool:
        block = np.asarray(samples, dtype=np.float32)
        rms = float(np.sqrt(np.mean(block ** 2))) if block.size else 0.0
        threshold = max(self.base_threshold, self._noise_floor * 1.5)
        if rms >= threshold:
            self.heard_voice = True
            self.silent_samples = 0
        elif self.heard_voice:
            self.silent_samples += block.size
        else:
            # Only update noise floor with silence samples, not speech
            self._noise_floor = (1 - self._ALPHA) * self._noise_floor + self._ALPHA * rms
        return self.heard_voice and self.silent_samples >= self.silence_duration_sec * self.sample_rate
