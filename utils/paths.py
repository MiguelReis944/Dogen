"""Resolve bundled resources and writable per-user application data."""

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """Whether Dogen is running from a PyInstaller-built application."""
    return bool(getattr(sys, "frozen", False))


def app_resource_root() -> Path:
    """Return the directory containing read-only application resources."""
    bundled_root = getattr(sys, "_MEIPASS", None)
    if is_frozen() and bundled_root:
        return Path(bundled_root)
    return Path(__file__).resolve().parents[1]


def app_data_root() -> Path:
    """Return the writable per-user data directory for packaged apps.

    Source runs intentionally keep the existing project-local settings and SQLite
    database behavior. Packaged installs use a per-user directory so updates in
    Program Files never overwrite or lose conversations and preferences.
    """
    if not is_frozen():
        return app_resource_root()

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "Dogen"


def settings_path() -> Path:
    return app_data_root() / "settings.json"


def conversations_path() -> Path:
    return app_data_root() / "conversations.db"


def setup_marker_path() -> Path:
    return app_data_root() / "first_run_setup_complete"


def configure_model_cache_dirs() -> None:
    """Place packaged speech-model caches beside other per-user app data."""
    if not is_frozen():
        return

    model_root = app_data_root() / "models"
    os.environ.setdefault("TTS_HOME", str(model_root / "tts"))
    os.environ.setdefault("XDG_CACHE_HOME", str(model_root / "cache"))
