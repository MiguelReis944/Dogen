from pathlib import Path

import pytest

from scripts.verify_bundle import verify_tts_config_sources


def test_bundle_validation_reports_missing_dynamic_tts_config_files(tmp_path):
    source_root = tmp_path / "site-packages" / "TTS"
    source_configs = source_root / "vocoder" / "configs"
    source_configs.mkdir(parents=True)
    (source_configs / "__init__.py").write_text("# config package", encoding="utf-8")
    (source_configs / "hifigan_config.py").write_text("class Config: pass", encoding="utf-8")

    bundled_root = tmp_path / "dist" / "Dogen"
    bundled_configs = bundled_root / "_internal" / "TTS" / "vocoder" / "configs"
    bundled_configs.mkdir(parents=True)
    (bundled_configs / "__init__.py").write_text("# config package", encoding="utf-8")

    with pytest.raises(RuntimeError, match="hifigan_config.py"):
        verify_tts_config_sources(bundled_root, source_root)


def test_bundle_validation_rejects_an_absent_tts_config_directory(tmp_path):
    source_root = tmp_path / "site-packages" / "TTS"
    source_configs = source_root / "vocoder" / "configs"
    source_configs.mkdir(parents=True)
    (source_configs / "__init__.py").write_text("# config package", encoding="utf-8")

    bundled_root = tmp_path / "dist" / "Dogen"
    bundled_root.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="__init__.py"):
        verify_tts_config_sources(bundled_root, source_root)


def test_bundle_validation_accepts_all_dynamic_tts_config_files(tmp_path):
    source_root = tmp_path / "site-packages" / "TTS"
    source_configs = source_root / "vocoder" / "configs"
    source_configs.mkdir(parents=True)
    expected = {"__init__.py", "hifigan_config.py"}
    for filename in expected:
        (source_configs / filename).write_text("# config source", encoding="utf-8")

    bundled_root = tmp_path / "dist" / "Dogen"
    bundled_configs = bundled_root / "_internal" / "TTS" / "vocoder" / "configs"
    bundled_configs.mkdir(parents=True)
    for filename in expected:
        (bundled_configs / filename).write_text("# config source", encoding="utf-8")

    assert verify_tts_config_sources(bundled_root, source_root) == 2
