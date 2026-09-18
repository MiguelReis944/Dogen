"""Local Whisper transcription. Model files must be cached before launch."""

from pathlib import Path


class Transcriber:
    def __init__(self, model_name="base"):
        import whisper

        models = whisper._MODELS
        if model_name in models:
            filename = models[model_name].split("/")[-1]
            if not (Path.home() / ".cache" / "whisper" / filename).is_file():
                raise FileNotFoundError(f"Whisper model {model_name!r} is not cached. See docs/SETUP.md")
        self.model = whisper.load_model(model_name)

    def transcribe(self, audio):
        return self.model.transcribe(audio, language="en", fp16=False)["text"].strip()
