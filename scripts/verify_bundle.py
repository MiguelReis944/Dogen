"""Check that the frozen app contains runtime-scanned Coqui TTS configs."""

import argparse
from importlib.util import find_spec
from pathlib import Path


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_root", type=Path)
    args = parser.parse_args()

    package_spec = find_spec("TTS")
    if not package_spec or not package_spec.submodule_search_locations:
        parser.error("coqui-tts is not available in the build environment")
    source_tts_root = Path(next(iter(package_spec.submodule_search_locations)))
    count = verify_tts_config_sources(args.bundle_root, source_tts_root)
    print(f"Verified {count} Coqui TTS vocoder config source files in the app bundle.")


if __name__ == "__main__":
    main()
