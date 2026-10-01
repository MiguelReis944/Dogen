from pathlib import Path

from utils import paths


def test_source_run_keeps_data_in_project_directory(monkeypatch, tmp_path):
    monkeypatch.delattr(paths.sys, "frozen", raising=False)
    monkeypatch.setattr(paths, "__file__", str(tmp_path / "utils" / "paths.py"))

    assert paths.app_resource_root() == tmp_path
    assert paths.app_data_root() == tmp_path
    assert paths.settings_path() == tmp_path / "settings.json"
    assert paths.conversations_path() == tmp_path / "conversations.db"


def test_frozen_app_uses_per_user_data_and_bundled_resources(monkeypatch, tmp_path):
    bundle_root = tmp_path / "bundle"
    local_app_data = tmp_path / "local"
    bundle_root.mkdir()
    local_app_data.mkdir()
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    assert paths.app_resource_root() == bundle_root
    assert paths.app_data_root() == local_app_data / "Dogen"
    assert paths.settings_path() == local_app_data / "Dogen" / "settings.json"
    assert paths.conversations_path() == local_app_data / "Dogen" / "conversations.db"


def test_packaged_model_caches_use_app_local_data_and_respect_overrides(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("TTS_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    paths.configure_model_cache_dirs()

    assert Path(paths.os.environ["TTS_HOME"]) == tmp_path / "local" / "Dogen" / "models" / "tts"
    assert Path(paths.os.environ["XDG_CACHE_HOME"]) == tmp_path / "local" / "Dogen" / "models" / "cache"

    monkeypatch.setenv("TTS_HOME", str(tmp_path / "custom-tts"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "custom-cache"))
    paths.configure_model_cache_dirs()

    assert Path(paths.os.environ["TTS_HOME"]) == tmp_path / "custom-tts"
    assert Path(paths.os.environ["XDG_CACHE_HOME"]) == tmp_path / "custom-cache"
