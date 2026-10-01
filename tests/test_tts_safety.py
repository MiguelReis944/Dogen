"""Synthetic audio fixtures exercise TTS safety without models or speakers."""

import sys
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.io import wavfile

from audio.player import Player
from nlp.synthesizer import Synthesizer, _trim_silence


def _synthesizer(samples, rate=22050):
    """Replace only Coqui inference; leave our audio handling real."""
    class FixedCoqui:
        synthesizer = SimpleNamespace(output_sample_rate=rate)
        splits = []

        def tts(self, text, split_sentences=True, **kwargs):
            self.splits.append(split_sentences)
            return samples

        def tts_to_file(self, text, file_path, **kwargs):
            # A real WAV boundary also reproduces the old peak normalization.
            wavfile.write(file_path, rate, np.asarray(samples, dtype=np.float32))

    synth = Synthesizer.__new__(Synthesizer)
    synth.tts = FixedCoqui()
    synth._speaker = None
    synth._cache = {}
    return synth


def _output_device(monkeypatch):
    played = []
    opened = []

    class OutputStream:
        def __init__(self, **kwargs):
            opened.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write(self, samples):
            played.append(samples.copy())

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(OutputStream=OutputStream))
    return played, opened


def test_streaming_synthesis_does_not_split_a_sentence_again_in_coqui():
    synth = _synthesizer(np.full(2205, 0.2, dtype=np.float32))

    chunks = list(synth.synthesize_stream("Good morning. Keep practicing."))

    assert len(chunks) == 2
    assert synth.tts.splits == [False, False]


def test_synthesis_uses_float_audio_without_wav_peak_amplification():
    synth = _synthesizer(np.full(2205, 0.01, dtype=np.float32))

    def unexpected_file(*_args, **_kwargs):
        raise AssertionError("Float synthesis must not pass through normalized WAV output")

    synth.tts.tts_to_file = unexpected_file
    samples, rate = synth.synthesize("Hello.")

    assert rate == 22050
    assert samples.dtype == np.float32
    assert float(samples.max()) == pytest.approx(0.01)


def test_silence_trim_removes_startup_padding_and_preserves_short_speech_edges():
    samples = np.concatenate((np.zeros(400), np.full(100, 0.2), np.zeros(600)))

    trimmed = _trim_silence(samples, 1000)

    assert len(trimmed) == 200
    np.testing.assert_array_equal(trimmed[:20], np.zeros(20))
    np.testing.assert_array_equal(trimmed[20:120], np.full(100, 0.2))
    np.testing.assert_array_equal(trimmed[120:], np.zeros(80))


@pytest.mark.parametrize("samples", [
    np.array([0.2, np.nan, 0.2]),
    np.array([0.2, np.inf, 0.2]),
    np.empty(0),
    np.zeros(22050),
    np.full((2205, 2), 0.2),
])
def test_synthesis_rejects_invalid_or_silent_output(samples):
    synth = _synthesizer(samples)

    with pytest.raises(ValueError, match="audio"):
        synth.synthesize("Hello.")


def test_synthesis_rejects_runaway_audio_for_a_short_sentence():
    synth = _synthesizer(np.full(22050 * 60, 0.2, dtype=np.float32))

    with pytest.raises(ValueError, match="duration"):
        synth.synthesize("Hello.")


def test_synthesis_preserves_a_normal_long_sentence():
    synth = _synthesizer(np.full(22050 * 15, 0.2, dtype=np.float32))
    text = "Today we can practice a longer sentence about the places you enjoy visiting and the activities you usually do on the weekend."

    samples, rate = synth.synthesize(text)

    assert len(samples) / rate == 15


@pytest.mark.parametrize("samples, expected", [
    (np.array([128, -128], dtype=np.int16), [0.00390625, -0.00390625]),
    (np.array([127, 128, 129], dtype=np.uint8), [-0.0078125, 0.0, 0.0078125]),
])
def test_player_preserves_quiet_pcm_volume(monkeypatch, samples, expected):
    played, _opened = _output_device(monkeypatch)

    Player().play(samples, 1000, lambda: False)

    np.testing.assert_allclose(np.concatenate(played).ravel(), expected)


@pytest.mark.parametrize("samples, rate", [
    (np.array([0.2, np.nan]), 22050),
    (np.array([0.2, np.inf]), 22050),
    (np.full((10, 2), 0.2), 22050),
    (np.array([0.2]), 0),
    (np.array([0.2]), -1),
])
def test_player_rejects_invalid_audio_before_opening_speakers(monkeypatch, samples, rate):
    _played, opened = _output_device(monkeypatch)

    with pytest.raises(ValueError, match="audio"):
        Player().play(samples, rate, lambda: False)

    assert opened == []


def test_player_clips_float_overload_without_boosting_quiet_audio(monkeypatch):
    played, _opened = _output_device(monkeypatch)

    Player().play(np.array([1.2, -1.2, 0.01]), 1000, lambda: False)

    np.testing.assert_allclose(np.concatenate(played).ravel(), [1.0, -1.0, 0.01])


def test_player_stop_remains_interruptible_between_audio_blocks(monkeypatch):
    played, _opened = _output_device(monkeypatch)
    volumes = []

    Player().play(np.full(300, 0.2), 1000, lambda: len(played) == 1, volumes.append)

    assert len(played) == 1
    assert len(played[0]) == 100
    assert volumes == [pytest.approx(0.2)]
