"""Check frozen Coqui sources and speech-tool data needed by the runtime."""

import argparse
import runpy
from importlib.util import find_spec
from pathlib import Path


TORCHSCRIPT_SOURCE_MODULES = (
    Path("vocoder") / "layers" / "wavegrad.py",
    Path("tts") / "layers" / "generic" / "wavenet.py",
)


def verify_tts_config_sources(bundle_root, source_tts_root):
    """Ensure every source config Coqui scans is present beside the frozen app."""
    source_configs = Path(source_tts_root) / "vocoder" / "configs"
    bundled_configs = (
        Path(bundle_root) / "_internal" / "TTS" / "vocoder" / "configs"
    )
    expected = {path.name for path in source_configs.glob("*.py")}
    actual = {path.name for path in bundled_configs.glob("*.py")}

    if not expected:
        raise RuntimeError(f"No Coqui TTS vocoder config sources found in {source_configs}")
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(
            "Dogen bundle is missing Coqui TTS vocoder config source files: "
            + ", ".join(missing)
        )
    return len(expected)


def verify_tts_torchscript_sources(bundle_root, source_tts_root):
    """Ensure PyTorch can inspect Coqui modules decorated with TorchScript."""
    checked = 0
    for relative_source in TORCHSCRIPT_SOURCE_MODULES:
        source_module = Path(source_tts_root) / relative_source
        bundled_module = Path(bundle_root) / "_internal" / "TTS" / relative_source

        if not source_module.is_file():
            raise RuntimeError(
                "Coqui TorchScript source file not found in build environment: "
                f"{source_module}"
            )
        if not bundled_module.is_file():
            relative_posix = relative_source.as_posix()
            raise RuntimeError(
                "Dogen bundle is missing the Coqui TorchScript source file: "
                f"TTS/{relative_posix}"
            )
        try:
            runpy.run_path(str(bundled_module))
        except Exception as exc:
            raise RuntimeError(
                "The Coqui TorchScript source file could not be loaded by PyTorch: "
                f"TTS/{relative_source.as_posix()}"
            ) from exc
        checked += 1
    return checked


def verify_inflect_source_files(bundle_root, source_inflect_root):
    """Ensure inflect's inspect/typeguard instrumentation can read real source."""
    source_root = Path(source_inflect_root)
    bundled_root = Path(bundle_root) / "_internal" / "inflect"
    expected = {
        path.relative_to(source_root)
        for path in source_root.rglob("*.py")
        if path.is_file()
    }
    actual = {
        path.relative_to(bundled_root)
        for path in bundled_root.rglob("*.py")
        if path.is_file()
    }

    if not expected:
        raise RuntimeError(f"No inflect Python source files found in {source_root}")
    missing = sorted(
        "inflect/" + str(path).replace("\\", "/") for path in expected - actual
    )
    if missing:
        raise RuntimeError(
            "Dogen bundle is missing inflect Python source files required by "
            "typeguard: " + ", ".join(missing)
        )
    return len(expected)


def verify_ko_speech_data_files(bundle_root, source_ko_speech_root):
    """Ensure ko-speech-tools' namespace-package resources are bundled."""
    source_data = Path(source_ko_speech_root) / "data"
    bundled_data = (
        Path(bundle_root) / "_internal" / "ko_speech_tools" / "data"
    )
    expected = {
        path.relative_to(source_data)
        for path in source_data.rglob("*")
        if path.is_file() and path.name != ".git"
    }
    actual = {
        path.relative_to(bundled_data)
        for path in bundled_data.rglob("*")
        if path.is_file() and path.name != ".git"
    }

    if not expected:
        raise RuntimeError(f"No ko_speech_tools.data resources found in {source_data}")
    missing = sorted(str(path) for path in expected - actual)
    if missing:
        raise RuntimeError(
            "Dogen bundle is missing ko_speech_tools.data namespace resources: "
            + ", ".join(missing)
        )
    return len(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_root", type=Path)
    args = parser.parse_args()

    package_spec = find_spec("TTS")
    if not package_spec or not package_spec.submodule_search_locations:
        parser.error("coqui-tts is not available in the build environment")
    source_tts_root = Path(next(iter(package_spec.submodule_search_locations)))
    count = verify_tts_config_sources(args.bundle_root, source_tts_root)
    torchscript_count = verify_tts_torchscript_sources(
        args.bundle_root, source_tts_root
    )
    package_spec = find_spec("inflect")
    if not package_spec or not package_spec.submodule_search_locations:
        parser.error("inflect is not available in the build environment")
    source_inflect_root = Path(next(iter(package_spec.submodule_search_locations)))
    inflect_source_count = verify_inflect_source_files(
        args.bundle_root, source_inflect_root
    )
    package_spec = find_spec("ko_speech_tools")
    if not package_spec or not package_spec.submodule_search_locations:
        parser.error("ko-speech-tools is not available in the build environment")
    source_ko_speech_root = Path(next(iter(package_spec.submodule_search_locations)))
    data_count = verify_ko_speech_data_files(
        args.bundle_root, source_ko_speech_root
    )
    print(
        f"Verified {count} Coqui TTS vocoder config sources and "
        f"{torchscript_count} Coqui TorchScript source files and "
        f"{inflect_source_count} inflect source files and "
        f"{data_count} ko-speech-tools data files in the app bundle."
    )


if __name__ == "__main__":
    main()
