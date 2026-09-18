"""Speaker playback, interruptible between 100 ms blocks."""

import numpy as np


class Player:
    def __init__(self, device=None):
        self.device = device

    def play(self, samples, sample_rate, cancelled, on_volume=None):
        import sounddevice as sd

        mono = np.asarray(samples, dtype=np.float32).reshape(-1)
        with sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32", device=self.device) as stream:
            block = max(1, sample_rate // 10)
            for offset in range(0, len(mono), block):
                if cancelled():
                    break
                chunk = mono[offset:offset + block]
                stream.write(chunk.reshape(-1, 1))
                if on_volume and chunk.size:
                    on_volume(float(np.sqrt(np.mean(chunk ** 2))))
