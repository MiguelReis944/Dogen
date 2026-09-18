"""Local Coqui synthesis using a temporary WAV file."""

import re
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
from scipy.io import wavfile

_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')


def _trim_silence(samples: np.ndarray, sample_rate: int,
                  threshold: float = 0.005, tail_ms: int = 80) -> np.ndarray:
    """Remove trailing silence that Coqui tacotron adds after each sentence."""
    block = max(1, sample_rate // 100)   # 10 ms blocks
    end = len(samples)
    while end > block:
        if float(np.sqrt(np.mean(samples[end - block:end] ** 2))) > threshold:
            break
        end -= block
    tail = int(tail_ms / 1000 * sample_rate)
    return samples[:min(len(samples), end + tail)]


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
        with NamedTemporaryFile(suffix=".wav", delete=False) as target:
            path = Path(target.name)
        try:
            kwargs = {"text": text, "file_path": str(path)}
            if self._speaker:
                kwargs["speaker"] = self._speaker
            self.tts.tts_to_file(**kwargs)
            sample_rate, samples = wavfile.read(path)
            if samples.dtype.kind in "iu":
                samples = samples.astype("float32") / max(
                    abs(float(samples.min())), abs(float(samples.max())), 1
                )
            return _trim_silence(samples, sample_rate), sample_rate
        finally:
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass  # Windows: TTS may still hold the handle briefly

    def synthesize(self, text: str) -> tuple:
        if text in self._cache:
            return self._cache[text]
        return self._synthesize_raw(text)

    def synthesize_stream(self, text: str):
        """Yield (samples, sample_rate) one sentence at a time for lower perceived latency."""
        sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
        for sentence in sentences or [text]:
            yield self.synthesize(sentence)
