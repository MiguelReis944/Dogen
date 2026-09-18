"""Local Coqui synthesis using a temporary WAV file."""

import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from scipy.io import wavfile

_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')


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

    def synthesize(self, text):
        with NamedTemporaryFile(suffix=".wav", delete=False) as target:
            path = Path(target.name)
        try:
            self.tts.tts_to_file(text=text, file_path=str(path))
            sample_rate, samples = wavfile.read(path)
            if samples.dtype.kind in "iu":
                samples = samples.astype("float32") / max(abs(float(samples.min())), abs(float(samples.max())), 1)
            return samples, sample_rate
        finally:
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass  # Windows: TTS may still hold the handle briefly

    def synthesize_stream(self, text):
        """Yield (samples, sample_rate) one sentence at a time for lower perceived latency."""
        sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
        for sentence in sentences or [text]:
            yield self.synthesize(sentence)
