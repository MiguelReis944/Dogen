"""Exercise ko-speech-tools resource loading in source and frozen builds."""

from importlib.resources import files


_NAMESPACE_RESOURCES = {
    "ko_speech_tools.data.cmudict": ("cmudict.dict",),
    "ko_speech_tools.data.g2p": ("idioms.txt", "rules.txt", "table.csv"),
    "ko_speech_tools.data.jamo": (
        "U+11xx.json",
        "U+31xx.json",
        "decompositions.json",
    ),
}


def verify_ko_speech_runtime():
    """Load the resources used by Coqui's Korean phonemizer."""
    resource_count = 0
    for package, names in _NAMESPACE_RESOURCES.items():
        package_resources = files(package)
        for name in names:
            with package_resources.joinpath(name).open("rb") as resource:
                if not resource.read(1):
                    raise RuntimeError(f"ko_speech_tools resource is empty: {package}/{name}")
            resource_count += 1

    from ko_speech_tools.g2p.cmudict import CMUDict
    from ko_speech_tools.g2p.utils import parse_table
    from ko_speech_tools.jamo import h2j

    if not h2j("한") or not len(CMUDict()) or not parse_table():
        raise RuntimeError("ko_speech_tools resources could not be parsed")
    return resource_count


if __name__ == "__main__":
    import sys

    if not getattr(sys, "frozen", False):
        raise SystemExit("This smoke test must run from its PyInstaller bundle.")
    count = verify_ko_speech_runtime()
    print(f"Loaded {count} ko_speech_tools resources from the frozen app.")
