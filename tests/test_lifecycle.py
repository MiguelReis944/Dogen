import pytest

from ui.lifecycle import CaptureState, transition


def test_capture_lifecycle_accepts_normal_and_recovery_transitions():
    assert transition(CaptureState.READY, CaptureState.RECORDING) is CaptureState.RECORDING
    assert transition(CaptureState.RECORDING, CaptureState.PROCESSING) is CaptureState.PROCESSING
    assert transition(CaptureState.ERROR, CaptureState.READY) is CaptureState.READY


def test_capture_lifecycle_treats_duplicate_state_as_idempotent():
    assert transition(CaptureState.RECORDING, CaptureState.RECORDING) is CaptureState.RECORDING


def test_capture_lifecycle_rejects_impossible_transitions():
    with pytest.raises(ValueError, match="shutdown"):
        transition(CaptureState.SHUTDOWN, CaptureState.READY)
    with pytest.raises(ValueError, match="Unknown"):
        transition("not-a-state", CaptureState.READY)
