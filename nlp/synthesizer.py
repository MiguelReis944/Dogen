"""Local Coqui synthesis using a temporary WAV file."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from scipy.io import wavfile


class Synthesizer:
    def __init__(self, model_name):
        from TTS.api import TTS
        from TTS.utils.manage import ModelManager
        import torch

        model_dir = Path(ModelManager(verbose=False).output_prefix) / model_name.replace("/", "--")
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
            path.unlink(missing_ok=True)
