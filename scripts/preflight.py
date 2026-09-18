"""Pre-flight checks: verify or download Whisper and TTS models."""

import sys


def check_whisper(model_name):
    import os
    import pathlib
    import whisper

    models = whisper._MODELS
    if model_name not in models:
        return True  # custom path, skip check
    filename = models[model_name].split("/")[-1]
    cache = pathlib.Path(os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache")) / "whisper"
    return (cache / filename).is_file()


def download_whisper(model_name):
    import whisper
    whisper.load_model(model_name)


def check_tts(model_name):
    import pathlib
    from TTS.utils.manage import ModelManager
    p = pathlib.Path(ModelManager().output_prefix) / model_name.replace("/", "--")
    return p.is_dir()


def download_tts(model_name):
    import torch
    import transformers.pytorch_utils as _p
    if not hasattr(_p, "isin_mps_friendly"):
        _p.isin_mps_friendly = torch.isin
    from TTS.api import TTS
    TTS(model_name)


COMMANDS = {
    "check-whisper": lambda args: sys.exit(0 if check_whisper(args[0]) else 1),
    "download-whisper": lambda args: download_whisper(args[0]),
    "check-tts": lambda args: sys.exit(0 if check_tts(args[0]) else 1),
    "download-tts": lambda args: download_tts(args[0]),
}

if __name__ == "__main__":
    cmd, *rest = sys.argv[1:]
    COMMANDS[cmd](rest)
