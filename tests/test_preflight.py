import builtins
import os
from pathlib import Path
import sys
from types import ModuleType

from scripts import preflight


def test_missing_runtime_modules_reports_unavailable_dependencies(monkeypatch):
    available = {"whisper", "torch", "torchaudio"}

    monkeypatch.setattr(
        preflight.importlib.util,
        "find_spec",
        lambda name: object() if name in available else None,
    )

    assert preflight.missing_runtime_modules() == ["TTS", "noisereduce"]


def test_transformers_compatibility_patch_is_optional(monkeypatch):
    real_import = builtins.__import__

    def import_without_transformers(name, *args, **kwargs):
        if name.startswith("transformers"):
            raise ModuleNotFoundError("No module named 'transformers'", name="transformers")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_transformers)

    assert preflight.patch_transformers_compatibility() is False


def test_tts_cache_check_patches_transformers_before_import(monkeypatch, tmp_path):
    patched = False

    def patch_transformers():
        nonlocal patched
        patched = True

    class FakeModelManager:
        def __init__(self):
            assert patched
            self.output_prefix = str(tmp_path)

    tts_module = ModuleType("TTS")
    utils_module = ModuleType("TTS.utils")
    manage_module = ModuleType("TTS.utils.manage")
    manage_module.ModelManager = FakeModelManager
    monkeypatch.setitem(sys.modules, "TTS", tts_module)
    monkeypatch.setitem(sys.modules, "TTS.utils", utils_module)
    monkeypatch.setitem(sys.modules, "TTS.utils.manage", manage_module)
    monkeypatch.setattr(preflight, "patch_transformers_compatibility", patch_transformers)

    model_name = "tts_models/en/ljspeech/tacotron2-DDC"
    (tmp_path / model_name.replace("/", "--")).mkdir()

    assert preflight.check_tts(model_name) is True


def test_tts_home_defaults_to_windows_local_app_data(monkeypatch, tmp_path):
    monkeypatch.delenv("TTS_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(preflight.sys, "platform", "win32")

    preflight.configure_tts_home()

    assert os.environ["TTS_HOME"] == str(tmp_path)


def test_start_validates_runtime_before_trusting_setup_marker():
    script = Path("start.bat").read_text(encoding="utf-8")

    tts_home = script.index('if not defined TTS_HOME set "TTS_HOME=%LOCALAPPDATA%"')
    runtime_check = script.index('"%PYTHON%" "%PREFLIGHT%" check-runtime')
    marker_jump = script.index("goto :after_setup")

    assert tts_home < runtime_check < marker_jump
