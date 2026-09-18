"""Local Coqui synthesis using a temporary WAV file."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from scipy.io import wavfile


class Synthesizer:
    def __init__(self, model_name):
        from TTS.api import TTS
        import torch

        self.tts = TTS(model_name=model_name, gpu=torch.cuda.is_available())

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
