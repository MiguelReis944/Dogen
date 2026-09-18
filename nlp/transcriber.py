"""Local Whisper transcription. Model files must be cached before launch."""

from pathlib import Path
from hashlib import sha256
import os


def _looks_like_silence(segments: list[dict], threshold: float = 0.6) -> bool:
    """Whisper hallucinates stock phrases ("Thank you for watching") on pure
    silence or background noise. If every segment thinks it's non-speech,
    trust that over the transcribed text."""
    return bool(segments) and all(seg.get("no_speech_prob", 0.0) > threshold for seg in segments)


class Transcriber:
    def __init__(self, model_name="base"):
        import whisper

        models = whisper._MODELS
        if model_name in models:
            filename = models[model_name].split("/")[-1]
            cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "whisper"
            model_path = cache_root / filename
            if not model_path.is_file():
                raise FileNotFoundError(f"Whisper model {model_name!r} is not cached. See docs/SETUP.md")
            expected_digest = models[model_name].split("/")[-2]
            if len(expected_digest) == 64 and sha256(model_path.read_bytes()).hexdigest() != expected_digest:
                raise ValueError(f"Cached Whisper model {model_name!r} failed checksum verification")
        self.model = whisper.load_model(model_name)

    def transcribe(self, audio):
        result = self.model.transcribe(audio, language="en", fp16=False)
        if _looks_like_silence(result.get("segments") or []):
            return ""
        return result["text"].strip()
