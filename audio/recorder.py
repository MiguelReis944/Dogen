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

    def record(self, cancelled):
        import sounddevice as sd

        blocks: Queue = Queue()
        detector = VoiceDetector(self.threshold, self.silence_duration_sec, self.sample_rate)
        chunks = []
        start = monotonic()

        def callback(indata, frames, time_info, status):
            if status:
                raise RuntimeError(str(status))
            blocks.put(indata[:, 0].copy())

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32", blocksize=1600,
                            device=self.device, callback=callback):
            while not cancelled() and monotonic() - start < 60:
                try:
                    chunk = blocks.get(timeout=0.1)
                except Empty:
                    continue
                chunks.append(chunk)
                if detector.feed(chunk) or (not detector.heard_voice and monotonic() - start >= 5):
                    break
        samples = np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)
        return samples if detector.heard_voice and samples.size >= int(0.2 * self.sample_rate) else np.empty(0, dtype=np.float32)
