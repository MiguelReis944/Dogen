from pathlib import Path

import pytest

from scripts.verify_bundle import (
    verify_ko_speech_data_files,
    verify_tts_config_sources,
)
from scripts.verify_ko_speech_runtime import verify_ko_speech_runtime


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


def test_bundle_validation_rejects_missing_ko_speech_namespace_data(tmp_path):
    source_root = tmp_path / "site-packages" / "ko_speech_tools"
    source_data = source_root / "data" / "jamo"
    source_data.mkdir(parents=True)
    (source_data / "decompositions.json").write_text("{}", encoding="utf-8")

    bundled_root = tmp_path / "dist" / "Dogen"
    bundled_root.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="decompositions.json"):
        verify_ko_speech_data_files(bundled_root, source_root)


def test_bundle_validation_accepts_all_ko_speech_namespace_data(tmp_path):
    source_root = tmp_path / "site-packages" / "ko_speech_tools"
    source_data = source_root / "data" / "jamo"
    source_data.mkdir(parents=True)
    expected = {"decompositions.json", "U+11xx.json"}
    for filename in expected:
        (source_data / filename).write_text("{}", encoding="utf-8")

    bundled_root = tmp_path / "dist" / "Dogen"
    bundled_data = (
        bundled_root / "_internal" / "ko_speech_tools" / "data" / "jamo"
    )
    bundled_data.mkdir(parents=True)
    for filename in expected:
        (bundled_data / filename).write_text("{}", encoding="utf-8")

    assert verify_ko_speech_data_files(bundled_root, source_root) == 2


def test_ko_speech_runtime_probe_reads_namespace_resources():
    assert verify_ko_speech_runtime() == 7
