# Daily Practice Release-Candidate Report

**Date:** 2026-09-27

**Status:** implementation complete; human acceptance pending

## Focus UI checkpoint — 2026-09-28

- `PYTHONPATH=. pytest -q`: 110 passed in the final run (11.45 seconds) after updating the existing Ollama fake to accept and assert `keep_alive=-1`. The first full run had 109 passed and one failure because that fake rejected the new argument; no product code changed for this checkpoint.
- `git diff --check`: exit code 0, with Git line-ending warnings for the edited report and `tests/test_core.py`, and no whitespace errors.
- Windows reported an input device (`Microfone (High Definition Audi`, index 1). A Dogen process started and Windows reported a window titled `Dogen`, but the available window-inspection tool did not return that window as a target. The process was stopped after this attempt.
- Therefore the maximized and minimum layouts, lower capture HUD, passive Today/Fixes, File actions, dialog backgrounds/logo, live microphone gating, replay/stop, and a second turn after idle **were not manually accepted** in this checkpoint. No screenshots or recordings were captured. Local microphone presence alone does not establish that an audio turn completed, and Ollama model retention was not measured in a live turn.
- Automated UI and pipeline regression tests passed, including the `keep_alive=-1` call expectation. They do not replace the pending visual and end-to-end checks.

## Inline review follow-up — 2026-09-30

- Added an approximate 15-minute conversation goal to Today. Its tooltip discloses
  that this duration is the span between the first and last completed turn, not
  measured microphone speaking time.
- Increased the shared interface font to 15px and applied the same HUD palette to
  native Windows title bars where the desktop compositor supports it.
- Focused regression tests cover the goal, font size, and requested title-bar colors.
- Visual inspection and real Ollama/audio idle-retention checks are still pending;
  these changes have not been manually accepted in the desktop app.

## Runtime bug-fix follow-up — 2026-09-30

- Today and Practice progress now sum captured PCM frames only; the wait between turns
  and model processing are excluded. Existing conversations are preserved, but their
  duration cannot be reconstructed and is not backfilled.
- File actions that affect session/configuration are enabled while the worker is idle
  between recordings and locked during capture/processing. Settings restart the worker
  between turns so changes actually reach the recorder and models.
- Structured feedback is recovered from legacy assistant messages. The empty Fixes
  panel now says when no correction was recorded.
- Partial model streams remain visible and persisted as interrupted messages, but do not
  enter future LLM context or count as completed turns. A TTS/playback failure no longer
  discards a successfully generated text response.
- Windows startup now sets a Dogen AppUserModelID before creating the Qt application.
  The automated API-call test passes; the taskbar icon still needs visual confirmation
  after restarting the app on Windows.
- Verification: `python -m pytest -q` — 131 passed; `git diff --check` — no whitespace
  errors.

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
| Automated tests and documentation are current | passed | 110 tests in the 2026-09-28 Focus UI checkpoint; README and setup updates predate it |

## Known limitations

- The formal transcription comparison remains pending until the same private recordings are run through all four model/denoise combinations.
- Legacy sessions have no captured-frame duration and therefore contribute zero recorded minutes; no elapsed-turn estimate is substituted.
- Legacy turns count as activity but cannot produce word, filler, or transcript-edit rates.
- Replay is available from the File menu while click-controlled recording is idle.

## Deferred work

- Pitch-preserving speech-speed control.
- Validated pronunciation assessment based on phoneme alignment and accent-aware calibration.
- Seven real days of at least 15 minutes of dogfooding.

The release must not be called fully validated until the pending manual acceptance rows are completed with real measurements.
