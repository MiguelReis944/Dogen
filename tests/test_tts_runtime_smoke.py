import sys
from types import ModuleType

from scripts import verify_tts_runtime


def test_frozen_voice_smoke_succeeds_without_cached_model(monkeypatch):
    checked_models = []
    monkeypatch.setattr(
        verify_tts_runtime,
        "check_tts",
        lambda model_name: checked_models.append(model_name) or False,
    )

    assert verify_tts_runtime.run_smoke_check() == 0
    assert checked_models == ["tts_models/en/ljspeech/tacotron2-DDC"]


def test_frozen_voice_smoke_reports_import_failure(monkeypatch):
    def fail_import(model_name):
        raise OSError("could not get source code")

    monkeypatch.setattr(verify_tts_runtime, "check_tts", fail_import)

    assert verify_tts_runtime.run_smoke_check() == 1


def test_frozen_smoke_redirects_numba_cache_to_build_temp_dir(monkeypatch, tmp_path):
    numba_module = ModuleType("numba")
    core_module = ModuleType("numba.core")
    caching_module = ModuleType("numba.core.caching")
    config_module = ModuleType("numba.core.config")
    core_module.caching = caching_module
    core_module.config = config_module
    numba_module.core = core_module
    monkeypatch.setitem(sys.modules, "numba", numba_module)
    monkeypatch.setitem(sys.modules, "numba.core", core_module)
    monkeypatch.setitem(sys.modules, "numba.core.caching", caching_module)
    monkeypatch.setitem(sys.modules, "numba.core.config", config_module)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("DOGEN_TTS_SMOKE_CACHE", str(tmp_path))

    verify_tts_runtime.redirect_numba_cache_for_smoke()

    cache_dirs = caching_module.AppDirs(appname="numba", appauthor=False)
    assert cache_dirs.user_cache_dir == str(tmp_path)
    assert config_module.CACHE_LOCATOR_CLASSES == "UserWideCacheLocator"
