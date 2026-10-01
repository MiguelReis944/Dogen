"""Small, local-only diagnostics with an explicit privacy allowlist."""

import json
import logging
import math
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PyQt5.QtCore import QStandardPaths

_LOGGER = logging.getLogger("dogen.diagnostics")
_HANDLER_MARKER = "_dogen_diagnostics_path"
_ALLOWED_EVENTS = {
    "state_transition",
    "recording_finished",
    "turn_started",
    "turn_finished",
    "turn_failed",
    "turn_interrupted",
    "audio_error",
    "persistence_error",
    "app_shutdown",
    "startup_failed",
    "stage_completed",
}
_ALLOWED_STATES = {"loading", "ready", "recording", "processing", "error", "shutdown"}
_ALLOWED_STAGES = {"startup", "capture", "transcribe", "model", "tts", "playback", "storage"}
_ALLOWED_STOP_REASONS = {"silence", "ptt_release", "timeout", "cancelled"}
_ALLOWED_MILESTONES = {
    ("model", "first_token"),
    ("model", "first_sentence_ready"),
    ("tts", "first_audio_ready"),
    ("tts", "synthesis_total"),
}
_SAFE_ERROR_TYPE = re.compile(r"^[A-Z][A-Za-z0-9_]{0,63}$")
_TRACE_ID = re.compile(r"^[a-f0-9]{32}$")


def local_diagnostics_path() -> Path | None:
    """Return the per-user app-data location, or None when unavailable."""
    location = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    return Path(location) / "diagnostics.log" if location else None


def disable_local_diagnostics() -> None:
    """Close the opt-in diagnostics sink immediately when the user disables it."""
    for handler in list(_LOGGER.handlers):
        if hasattr(handler, _HANDLER_MARKER):
            _LOGGER.removeHandler(handler)
            handler.close()


def configure_local_diagnostics(path: str | Path) -> bool:
    """Write privacy-filtered diagnostic events to a small rotating local log."""
    try:
        resolved_path = Path(path).resolve()
    except (OSError, RuntimeError):
        disable_local_diagnostics()
        return False
    for handler in _LOGGER.handlers:
        if getattr(handler, _HANDLER_MARKER, None) == resolved_path:
            return True
    disable_local_diagnostics()

    try:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            resolved_path,
            maxBytes=512_000,
            backupCount=2,
            encoding="utf-8",
        )
    except OSError:
        return False
    handler.setFormatter(logging.Formatter("%(message)s"))
    setattr(handler, _HANDLER_MARKER, resolved_path)
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False
    return True


def log_diagnostic(event: str, **fields) -> None:
    """Emit an allowlisted event; arbitrary text and unknown keys are discarded."""
    if not isinstance(event, str) or event not in _ALLOWED_EVENTS or not any(
        hasattr(handler, _HANDLER_MARKER) for handler in _LOGGER.handlers
    ):
        return

    payload = {"event": event}
    for key, value in fields.items():
        if key == "state" and isinstance(value, str) and value in _ALLOWED_STATES:
            payload[key] = value
        elif key == "stage" and isinstance(value, str) and value in _ALLOWED_STAGES:
            payload[key] = value
        elif (
            key == "milestone"
            and event == "stage_completed"
            and isinstance(value, str)
            and (fields.get("stage"), value) in _ALLOWED_MILESTONES
        ):
            payload[key] = value
        elif (
            key == "stop_reason"
            and isinstance(value, str)
            and value in _ALLOWED_STOP_REASONS
        ):
            payload[key] = value
        elif key == "error_type" and isinstance(value, str) and _SAFE_ERROR_TYPE.fullmatch(value):
            payload[key] = value
        elif key == "trace_id" and isinstance(value, str) and _TRACE_ID.fullmatch(value):
            payload[key] = value
        elif (
            key in {"duration_ms", "duration_sec"}
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            numeric_value = float(value)
            if math.isfinite(numeric_value) and 0 <= numeric_value <= 86_400_000:
                payload[key] = int(value) if isinstance(value, int) else numeric_value

    _LOGGER.info(json.dumps(payload, sort_keys=True, separators=(",", ":")))
