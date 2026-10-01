# Daily Practice Release-Candidate Report

**Date:** 2026-09-27

**Status:** implementation complete; human acceptance pending

## Narration and Fixes follow-up — 2026-10-01

- Coaching blocks are filtered before streaming text reaches the conversation or
  sentence segmentation. Incomplete and nested annotations cannot become narration;
  old Grammar/Agreement comments are hidden on rendering and removed from model context
  without rewriting the saved conversation.
- Fixes accepts a brief correction pair grounded in the current transcript. Known
  contraction, punctuation and optional style rewrites are rejected. Better-phrasing
  blocks and category-only notes do not become learner feedback.
- A bounded producer prepares audio while the preceding chunk plays, including Replay.
  Synthesis calls are serialized across an interrupted producer and subsequent turns.
  Text remains saved if synthesis or playback fails.
- Coqui now returns float audio in memory. This avoids WAV peak normalization and
  Coqui's extra sentence splitting, whose installed implementation pads each split
  with 10,000 samples (453.5 ms at 22,050 Hz). Leading/trailing padding is trimmed with
  short speech edges preserved. Invalid, nonfinite, silent or excessively long output
  is rejected before speaker playback.
- Silent checks of the cached female model on CPU synthesized three public test phrases
  in 0.425, 0.858 and 4.031 seconds. No output was played through speakers or saved as
  an audio file. These checks measure synthesis only, excluding Python import, Whisper,
  Ollama and playback. Intermittent audible artifacts and the whole spoken turn still
  require real-device acceptance.
- A small six-case corpus using the local Ollama model and the actual runtime settings
  accepted three substantive errors and rejected three false fixes after filtering.
  The model still generated optional rewrites that the filters rejected. Two additional
  gerund-error probes produced valid fixes but also unnecessary surrounding wording
  changes. These checks are not a general accuracy benchmark or proof of optimal fixes.
- Review identified a stale-producer cancellation race after Stop. A persistent
  per-operation cancellation event and cancellation-aware synthesis-lock acquisition
  now prevent queued work from restarting after interruption. A synchronous synthesis
  already in progress can still finish, without playing its canceled output.
- Verification: `python -m pytest -q -p no:cacheprovider` — 255 passed in 29.47s.
  Regression coverage includes fragmented coaching markup, passive Fixes, saved-history
  rendering, audio guards, prefetch, persistent cancellation and response preservation
  after audio failure. The follow-up review found no remaining Important findings.

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

## Today metrics and settings follow-up — 2026-09-30

- The daily captured-audio goal is configurable in Settings and defaults to 15 minutes;
  legacy `settings.json` files receive the default without migration.
- Today now presents captured audio once, as progress toward the configured goal. Word
  and filler counts are labeled as transcript-derived, coach corrections are distinguished
  from all learner errors, and the practice-streak tooltip explains interrupted attempts.
- Today includes corrections recovered from legacy assistant annotations without counting
  the same structured feedback twice.
- Today and Practice progress use the same attempt-based practice-day/streak definition;
  completed-turn totals still exclude interrupted responses.
- Windows startup now sets a Dogen AppUserModelID before creating the Qt application.
  The automated API-call test passes; the taskbar icon still needs visual confirmation
  after restarting the app on Windows.
- Verification: `python -m pytest -q` — 131 passed; `git diff --check` — no whitespace
  errors.

## Video reliability and architecture follow-up — 2026-09-30

- The active same-day session ID is restored after restart; starting a new session
  persists its new ID. An empty session now reports that there is nothing to export
  instead of creating a blank file.
- Interrupted model/TTS turns keep the transcript and any generated response visible,
  stored, and exportable, while remaining outside future model context and completed-turn
  metrics. Cancellation while waiting for the first model sentence remains responsive.
- The Today panel now reads the same date-window aggregate as Practice Progress. A local,
  content-free turn ID links stage durations to the persisted completion/interruption.
- `ConversationWorker` now lives in `ui/conversation_worker.py`; capture state changes are
  validated through an explicit lifecycle enum. The barge-in microphone stream is closed
  before the next capture and during worker shutdown.
- Reliability diagnostics are off by default, stay in the user's local app-data folder,
  rotate at 512 KB with two backups, and can be disabled immediately. Tests verify that
  recognizable private text and arbitrary error identifiers are not written.
- Verification: `python -m pytest -q -p no:cacheprovider` — 176 passed in 18.48s;
  `python -m compileall -q main.py pipeline.py ui storage audio utils` and
  `git diff --check` also passed.
- Manual microphone/Ollama/TTS use, a fresh Windows taskbar-icon check, vocabulary table
  appearance, and the seven-day dogfood check remain pending. Automated tests cannot
  confirm those desktop and real-device results.

## Ollama model-selection and VRAM follow-up — 2026-10-01

- Startup still loads Whisper and the local voice, but no longer preloads the configured
  LLM. The installed-model list and the last selected preference are resolved before an
  explicit **Load selected model** action can warm an LLM.
- File → Model distinguishes the selection, Dogen's model for the next turn, the model
  used for the last response, and the global resident-model/VRAM snapshot from Ollama.
  Ollama does not report which client owns resident models.
- Switching explicitly releases Dogen's previously activated model before warming the
  newly selected one. Conversation requests retain models for five minutes after use,
  instead of indefinitely. Other resident models are not unloaded silently; a separate
  confirmed action warns that unloading them affects every app using the shared Ollama
  server.
- Automated coverage includes the startup wait-for-choice state, unload-before-load
  ordering, finite retention, shared VRAM reporting, explicit cross-app unload warning,
  and exact model attribution in Dogen's selection/turn records.
- Manual acceptance is still required to confirm VRAM release and compare stronger models
  on the user's RX 7600 8 GB. A model left resident by an earlier app version can be seen
  in the menu; freeing it requires the confirmed action or restarting the Ollama service.

## Environment

- Operating system: Windows
- Python: 3.10.11
- Compute path: CPU PyTorch
- Microphone: not identified from the supplied recording
- Whisper default: `small.en`
- Startup: Whisper/voice load automatically; Ollama LLM requires explicit selection/load
- Input: click once to start recording and once to finish
- Noise reduction default: enabled
- TTS default: `tts_models/en/ljspeech/tacotron2-DDC`
- Initial LLM preference: local Ollama `mistral`; no model is loaded until selected

## Automated verification

Executed in the Dogen checkout on 2026-10-01:

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.venv\Scripts\python.exe -m pip check
```

Result:

- 263 tests passed in 33.34 seconds;
- no broken Python requirements;
- `ui`, `nlp`, and `tests` compile without syntax errors;
- `git diff --check` reported no whitespace errors (only Git line-ending notices).

The pytest cache plugin is disabled in this checkout to avoid creating `.pytest_cache`. It does not change which tests run.

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
