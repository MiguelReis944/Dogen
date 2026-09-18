"""Speaker playback, interruptible between 100 ms blocks."""

import numpy as np


class Player:
    def __init__(self, device=None):
        self.device = device

    def play(self, samples, sample_rate, cancelled):
        import sounddevice as sd

        mono = np.asarray(samples, dtype=np.float32).reshape(-1)
        with sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32", device=self.device) as stream:
            block = max(1, sample_rate // 10)
            for offset in range(0, len(mono), block):
                if cancelled():
                    break
                stream.write(mono[offset:offset + block].reshape(-1, 1))
