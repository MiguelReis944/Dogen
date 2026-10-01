"""Local Coqui synthesis with validated in-memory audio."""

import re
from pathlib import Path

import numpy as np

_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')


def _trim_silence(samples: np.ndarray, sample_rate: int,
                  threshold: float = 0.005, tail_ms: int = 80,
                  head_ms: int = 20) -> np.ndarray:
    """Keep short speech edges while removing Coqui's sentence padding."""
    block = max(1, sample_rate // 100)   # 10 ms blocks
    start = 0
    while start < len(samples):
        if float(np.sqrt(np.mean(samples[start:start + block] ** 2))) > threshold:
            break
        start += block
    if start >= len(samples):
        return samples[:0]
    end = len(samples)
    while end > start:
        if float(np.sqrt(np.mean(samples[max(start, end - block):end] ** 2))) > threshold:
            break
        end -= block
    head = int(head_ms / 1000 * sample_rate)
    tail = int(tail_ms / 1000 * sample_rate)
    return samples[max(0, start - head):min(len(samples), end + tail)]


# Short fixed phrases that Dogen says often enough to be worth caching on startup.
_CACHEABLE = [
    "Didn't catch that. Please try again.",
    "Sorry, something went wrong. Please try again.",
]


def _patch_transformers():
    """Inject isin_mps_friendly removed in transformers>=4.36 before TTS import."""
    try:
        import transformers.pytorch_utils as _p
        if not hasattr(_p, "isin_mps_friendly"):
            import torch
            _p.isin_mps_friendly = torch.isin
    except Exception:
        pass


class Synthesizer:
    def __init__(self, model_name):
        _patch_transformers()
        from TTS.api import TTS
        from TTS.utils.manage import ModelManager
        import torch

        model_dir = Path(ModelManager().output_prefix) / model_name.replace("/", "--")
        if not model_dir.is_dir():
            raise FileNotFoundError(f"Coqui model {model_name!r} is not cached. See docs/SETUP.md")
        self.tts = TTS(model_name).to("cuda" if torch.cuda.is_available() else "cpu")
        self._speaker: str | None = None
        self._cache: dict[str, tuple] = {}
        self._warm_cache()

    def _warm_cache(self):
        for phrase in _CACHEABLE:
            try:
                self._cache[phrase] = self._synthesize_raw(phrase)
            except Exception:
                pass

    def _synthesize_raw(self, text: str) -> tuple:
        # We already stream one sentence at a time. Coqui's second split adds
        # silence between fragments; its WAV writer also boosts quiet noise.
        kwargs = {"text": text, "split_sentences": False}
        if self._speaker:
            kwargs["speaker"] = self._speaker
        samples = np.asarray(self.tts.tts(**kwargs), dtype=np.float32)
        sample_rate = self.tts.synthesizer.output_sample_rate
        if (not isinstance(sample_rate, (int, np.integer)) or sample_rate <= 0
                or samples.ndim != 1 or not samples.size
                or not np.isfinite(samples).all()):
            raise ValueError("The voice model returned invalid audio.")
        samples = _trim_silence(np.clip(samples, -1.0, 1.0), sample_rate)
        if not samples.size:
            raise ValueError("The voice model returned silent audio.")
        # A generous slow-speech limit catches Tacotron decoder runaway instead
        # of playing a long noisy waveform for a short phrase.
        max_duration = max(8.0, len(text) * 0.12)
        if len(samples) / sample_rate > max_duration:
            raise ValueError("The voice model returned an excessive audio duration.")
        return samples, sample_rate

    def synthesize(self, text: str) -> tuple:
        if text in self._cache:
            return self._cache[text]
        return self._synthesize_raw(text)

    def synthesize_stream(self, text: str):
        """Yield (samples, sample_rate) one sentence at a time for lower perceived latency."""
        sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
        for sentence in sentences or [text]:
            yield self.synthesize(sentence)
