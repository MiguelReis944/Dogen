"""Microphone capture with end-of-speech detection."""

from queue import Empty, Queue
from time import monotonic

import numpy as np

from audio.vad import VoiceDetector


class Recorder:
    sample_rate = 16000

    def __init__(self, device=None, threshold=0.02, silence_duration_sec=2.0):
        self.device = device
        self.threshold = threshold
        self.silence_duration_sec = silence_duration_sec

    def record(self, cancelled, on_volume=None, stop_fn=None):
        """Record audio until end of utterance.

        stop_fn — if provided (PTT mode), recording stops when stop_fn() is True.
        on_volume(rms) — optional callback for live level meter.
        """
        import sounddevice as sd

        blocks: Queue = Queue()
        detector = VoiceDetector(self.threshold, self.silence_duration_sec, self.sample_rate)
        chunks = []
        start = monotonic()

        def callback(indata, frames, time_info, status):
            if status:
                blocks.put(RuntimeError(str(status)))
                return
            chunk = indata[:, 0].copy()
            blocks.put(chunk)
            if on_volume:
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                on_volume(rms)

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32",
                            blocksize=1600, device=self.device, callback=callback):
            while not cancelled() and monotonic() - start < 60:
                try:
                    chunk = blocks.get(timeout=0.1)
                except Empty:
                    continue
                if isinstance(chunk, Exception):
                    raise chunk
                chunks.append(chunk)
                if stop_fn is not None:
                    if stop_fn():
                        break
                else:
                    if detector.feed(chunk) or (not detector.heard_voice and monotonic() - start >= 5):
                        break

        samples = np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)
        min_samples = int(0.2 * self.sample_rate)
        has_audio = (stop_fn is not None) or (detector.heard_voice)
        if not has_audio or samples.size < min_samples:
            return np.empty(0, dtype=np.float32)
        return _denoise(samples, self.sample_rate)


def _denoise(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Spectral noise reduction applied once after recording ends."""
    try:
        import noisereduce as nr
        return nr.reduce_noise(y=samples, sr=sample_rate, stationary=False,
                               prop_decrease=0.75).astype(np.float32)
    except Exception:
        return samples
