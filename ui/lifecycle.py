"""Explicit capture/application lifecycle states and legal transitions."""

from enum import Enum


class CaptureState(str, Enum):
    LOADING = "loading"
    READY = "ready"
    RECORDING = "recording"
    PROCESSING = "processing"
    ERROR = "error"
    SHUTDOWN = "shutdown"


_ALLOWED_TRANSITIONS = {
    CaptureState.LOADING: {
        CaptureState.READY,
        CaptureState.RECORDING,
        CaptureState.PROCESSING,
        CaptureState.ERROR,
        CaptureState.SHUTDOWN,
    },
    CaptureState.READY: {
        CaptureState.LOADING,
        CaptureState.RECORDING,
        CaptureState.PROCESSING,
        CaptureState.ERROR,
        CaptureState.SHUTDOWN,
    },
    CaptureState.RECORDING: {
        CaptureState.READY,
        CaptureState.PROCESSING,
        CaptureState.ERROR,
        CaptureState.SHUTDOWN,
    },
    CaptureState.PROCESSING: {
        CaptureState.READY,
        CaptureState.RECORDING,
        CaptureState.ERROR,
        CaptureState.SHUTDOWN,
    },
    CaptureState.ERROR: {
        CaptureState.LOADING,
        CaptureState.READY,
        CaptureState.RECORDING,
        CaptureState.SHUTDOWN,
    },
    CaptureState.SHUTDOWN: set(),
}


def transition(current: CaptureState | str, target: CaptureState | str) -> CaptureState:
    """Validate and return the next state; repeated states are harmless no-ops."""
    try:
        current_state = CaptureState(current)
        target_state = CaptureState(target)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Unknown lifecycle state: {exc}") from exc

    if current_state == target_state:
        return current_state
    if target_state not in _ALLOWED_TRANSITIONS[current_state]:
        raise ValueError(
            f"Invalid lifecycle transition: {current_state.value} -> {target_state.value}"
        )
    return target_state
