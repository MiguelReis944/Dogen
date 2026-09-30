"""Microphone capture with end-of-speech detection."""

from dataclasses import dataclass
from queue import Empty, Queue
from time import monotonic
from typing import Literal

import numpy as np

from audio.vad import VoiceDetector


@dataclass(frozen=True)
class RecordingResult:
    samples: np.ndarray
    stop_reason: Literal["silence", "ptt_release", "timeout", "cancelled"]
    duration_sec: float


class Recorder:
    sample_rate = 16000

    def __init__(self, device=None, threshold=0.02, silence_duration_sec=2.0,
                 noise_reduction=True):
        self.device = device
        self.threshold = threshold
        self.silence_duration_sec = silence_duration_sec
        self.noise_reduction = noise_reduction
        self._noise_floor = 0.0  # carried across turns so the room's noise floor keeps adapting

    def record(self, cancelled, on_volume=None, stop_fn=None):
        """Record audio until end of utterance.

        stop_fn — if provided (PTT mode), recording stops when stop_fn() is True.
        on_volume(rms) — optional callback for live level meter.
        """
        import sounddevice as sd

        blocks: Queue = Queue()
        detector = VoiceDetector(self.threshold, self.silence_duration_sec, self.sample_rate,
                                 initial_noise_floor=self._noise_floor)
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

        stop_reason = "timeout"
        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32",
                            blocksize=1600, device=self.device, callback=callback):
            while True:
                if cancelled():
                    stop_reason = "cancelled"
                    break
                if monotonic() - start >= 60:
                    stop_reason = "timeout"
                    break
                try:
                    chunk = blocks.get(timeout=0.1)
                except Empty:
                    continue
                if isinstance(chunk, Exception):
                    raise chunk
                chunks.append(chunk)
                if stop_fn is not None:
                    if stop_fn():
                        stop_reason = "ptt_release"
                        break
                else:
                    if detector.feed(chunk) or (not detector.heard_voice and monotonic() - start >= 5):
                        stop_reason = "silence"
                        break

        if stop_fn is None:
            self._noise_floor = detector.noise_floor

        # Count only captured PCM frames. Wall-clock elapsed time includes stream
        # setup, processing pauses, and empty waits where no audio was recorded.
        duration_sec = sum(chunk.size for chunk in chunks) / self.sample_rate
        samples = (
            np.concatenate(chunks).astype(np.float32, copy=False)
            if chunks
            else np.empty(0, dtype=np.float32)
        )
        min_samples = int(0.2 * self.sample_rate)
        has_audio = (stop_fn is not None) or (detector.heard_voice)
        if not has_audio or samples.size < min_samples:
            samples = np.empty(0, dtype=np.float32)
        elif self.noise_reduction:
            samples = _denoise(samples, self.sample_rate).astype(np.float32, copy=False)
        return RecordingResult(samples, stop_reason, duration_sec)


def _denoise(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Spectral noise reduction applied once after recording ends."""
    try:
        import noisereduce as nr
        return nr.reduce_noise(y=samples, sr=sample_rate, stationary=False,
                               prop_decrease=0.75).astype(np.float32)
    except Exception:
        return samples
