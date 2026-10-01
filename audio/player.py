"""Speaker playback, interruptible between 100 ms blocks."""

import numpy as np


class Player:
    def __init__(self, device=None):
        self.device = device

    def play(self, samples, sample_rate, cancelled, on_volume=None):
        mono = np.asarray(samples)
        if (not isinstance(sample_rate, (int, np.integer)) or sample_rate <= 0
                or mono.ndim != 1 or mono.dtype.kind not in "fiu"
                or not np.isfinite(mono).all()):
            raise ValueError("Invalid audio for playback.")
        if not mono.size or cancelled():
            return
        if mono.dtype.kind in "iu":
            limits = np.iinfo(mono.dtype)
            scale = float(max(abs(limits.min), abs(limits.max) + 1))
            midpoint = scale / 2 if mono.dtype.kind == "u" else 0.0
            if mono.dtype.kind == "u":
                scale = midpoint
            mono = (mono.astype(np.float32) - midpoint) / scale
        else:
            mono = mono.astype(np.float32)
        mono = np.clip(mono, -1.0, 1.0)

        import sounddevice as sd
        with sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32", device=self.device) as stream:
            block = max(1, sample_rate // 10)
            for offset in range(0, len(mono), block):
                if cancelled():
                    break
                chunk = mono[offset:offset + block]
                stream.write(chunk.reshape(-1, 1))
                if on_volume and chunk.size:
                    on_volume(float(np.sqrt(np.mean(chunk ** 2))))
