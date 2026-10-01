"""Set model-cache locations before packaged dependencies are imported."""

import os
import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    cache_root = base / "Dogen" / "models"
    os.environ.setdefault("TTS_HOME", str(cache_root / "tts"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root / "cache"))
