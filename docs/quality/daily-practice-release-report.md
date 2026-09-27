# Daily Practice Release-Candidate Report

**Date:** 2026-09-27

**Status:** implementation complete; human acceptance pending

## Environment

- Operating system: Windows
- Python: 3.10.11
- Compute path: CPU PyTorch
- Microphone: not identified from the supplied recording
- Whisper default: `small.en`
- Startup: speech recognition, voice, and Ollama model load automatically
- Input: click once to start recording and once to finish
- Noise reduction default: enabled
- TTS default: `tts_models/en/ljspeech/tacotron2-DDC`
- LLM default: local Ollama `mistral`

## Automated verification

Executed from the isolated Dogen worktree:

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.venv\Scripts\python.exe -m pip check
```

Result:

- 91 tests passed in 9.12 seconds;
- no broken Python requirements;
- all 35 Python source files compiled in memory without syntax errors;
- `git diff --check` reported no whitespace errors.

The pytest cache plugin is disabled only in the managed worktree because its sandbox cannot create `.pytest_cache`. It does not change which tests run.

## Field evidence

The private video `2026-09-26 15-46-44.mp4` was inspected without copying it into the repository.

- duration: 96.6 seconds;
- resolution: 1920×1080 at 60 fps;
- learner submissions observed: 2;
- assistant responses observed: 2;
- crashes, stuck turns, or reported premature cuts: 0;
- known recognition error: `upgrade` was displayed as `pigrade`.

This is evidence that the original end-to-end loop operated, not a statistically valid accuracy benchmark.

## Voice evidence

LJSpeech loaded in 14.785 seconds and synthesized five fixed sentences in 0.611–0.827 seconds each on CPU. LJSpeech is now the only voice exposed by the product.

## Acceptance status

| Criterion | Status | Evidence |
|---|---|---|
| Click-controlled recording does not cut 20 test utterances | pending | requires learner microphone protocol |
| Transcript edits improve by at least 30% | pending | evaluator exists; private 120-attempt corpus not recorded |
| Stop and replay do not add turns | passed automatically | pipeline and UI regression tests |
| Coaching text is never sent to TTS | passed automatically | clean-speech pipeline tests |
| Feedback is separate and categorized | passed automatically | parser, database, pipeline, and UI tests |
| Weekly progress handles empty and legacy data | passed automatically | progress aggregate and UI tests |
| Ten consecutive manual conversations complete | pending | requires manual use |
| Automated tests and documentation are current | passed | 91 tests plus README and setup updates |

## Known limitations

- The formal transcription comparison remains pending until the same private recordings are run through all four model/denoise combinations.
- Practice time is the interval between the first and last completed turn in each session; a one-turn session contributes zero measured minutes.
- Legacy turns count as activity but cannot produce word, filler, or transcript-edit rates.
- Replay is available from the File menu while click-controlled recording is idle.

## Deferred work

- Pitch-preserving speech-speed control.
- Validated pronunciation assessment based on phoneme alignment and accent-aware calibration.
- Seven real days of at least 15 minutes of dogfooding.

The release must not be called fully validated until the pending manual acceptance rows are completed with real measurements.
