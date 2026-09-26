"""Pre-flight checks: verify or download Whisper and TTS models."""

import importlib.util
import os
import sys


REQUIRED_RUNTIME_MODULES = ("whisper", "TTS", "noisereduce", "torch", "torchaudio")


def configure_tts_home():
    """Avoid Coqui's fragile Windows registry lookup when LOCALAPPDATA is available."""
    if sys.platform == "win32" and "TTS_HOME" not in os.environ:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            os.environ["TTS_HOME"] = local_app_data


def missing_runtime_modules():
    return [
        module_name
        for module_name in REQUIRED_RUNTIME_MODULES
        if importlib.util.find_spec(module_name) is None
    ]


def check_runtime():
    missing = missing_runtime_modules()
    if missing:
        print("Missing runtime modules: " + ", ".join(missing), file=sys.stderr)
        return False
    return True


def patch_transformers_compatibility():
    """Patch older Coqui integrations when transformers is installed."""
    try:
        import transformers.pytorch_utils as pytorch_utils
    except ModuleNotFoundError as error:
        if error.name == "transformers" or error.name.startswith("transformers."):
            return False
        raise

    if not hasattr(pytorch_utils, "isin_mps_friendly"):
        import torch
        pytorch_utils.isin_mps_friendly = torch.isin
    return True


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
    configure_tts_home()
    patch_transformers_compatibility()
    from TTS.utils.manage import ModelManager
    p = pathlib.Path(ModelManager().output_prefix) / model_name.replace("/", "--")
    return p.is_dir()


def download_tts(model_name):
    configure_tts_home()
    patch_transformers_compatibility()
    from TTS.api import TTS
    TTS(model_name)


COMMANDS = {
    "check-runtime": lambda args: sys.exit(0 if check_runtime() else 1),
    "check-whisper": lambda args: sys.exit(0 if check_whisper(args[0]) else 1),
    "download-whisper": lambda args: download_whisper(args[0]),
    "check-tts": lambda args: sys.exit(0 if check_tts(args[0]) else 1),
    "download-tts": lambda args: download_tts(args[0]),
}

if __name__ == "__main__":
    cmd, *rest = sys.argv[1:]
    COMMANDS[cmd](rest)
