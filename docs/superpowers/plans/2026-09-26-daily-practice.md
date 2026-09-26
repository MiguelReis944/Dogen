# Dogen Daily Practice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Dogen into a reliable, private, offline English conversation coach suitable for 15–30 minutes of daily use.

**Architecture:** Preserve the existing PyQt worker and linear audio pipeline. Add typed results at capture and turn boundaries, keep coaching parsing in one module, persist objective per-turn metrics in SQLite, and derive progress in a dedicated query layer. Prefer explicit calls and signals over new infrastructure.

**Tech Stack:** Python 3.10+, PyQt5, NumPy, sounddevice, OpenAI Whisper, Ollama, Coqui TTS, SQLite, pytest.

**Spec:** `docs/design/2026-09-26-daily-practice-design.md`

## Global Constraints

- Remain offline-first. Do not add analytics, cloud storage, accounts, or remote speech APIs.
- Never commit the user's voice recordings, transcript benchmark corpus, database, generated audio, or model files.
- Keep push-to-talk functional after every checkpoint; it is the reliable fallback while VAD is tuned.
- Do not display pronunciation or proficiency scores without a separately validated scoring design.
- Do not replace the current architecture with an event bus, framework, or service layer.
- Complete each task with its focused tests, the full test suite, and a local commit before continuing.

---

## Task 1: Establish the daily-practice baseline

**Files:**
- Create: `docs/quality/daily-practice-baseline.md`
- Modify: `.gitignore`

- [ ] **Step 1: Protect private evaluation artifacts**

Add these repository-relative patterns to `.gitignore`:

```gitignore
local-evaluation/
*.evaluation.json
```

Run:

```powershell
git check-ignore local-evaluation/sample.wav result.evaluation.json
```

Expected: both paths are printed.

- [ ] **Step 2: Write the repeatable baseline protocol**

Create `docs/quality/daily-practice-baseline.md` with exactly these test sets:

- 10 short utterances of 3–7 words;
- 10 natural utterances containing a pause of 1–2 seconds;
- 10 utterances containing names, technical words, or numbers;
- the same 30 utterances in push-to-talk and automatic mode;
- one quiet-room run and one normal-background-noise run.

Record for each utterance: expected text, captured duration, stop reason, transcript, whether manual editing was needed, and time to first audible response. Store recordings and results under ignored `local-evaluation/`.

- [ ] **Step 3: Capture the current baseline before behavior changes**

Run the app with the current settings and complete the protocol. Document only aggregate results in the tracked file:

```text
premature cuts / attempts
manual transcript edits / attempts
median time to first audible response
failed or stuck turns / attempts
```

Do not tune settings during this run.

- [ ] **Step 4: Verify the repository remains private and healthy**

Run:

```powershell
git status --short
pytest -q
```

Expected: evaluation recordings do not appear in status; the existing suite passes.

- [ ] **Step 5: Commit the checkpoint**

```powershell
git add .gitignore docs/quality/daily-practice-baseline.md
git commit -m "docs: registrar baseline de pratica diaria"
```

---

## Task 2: Make recording endings observable and retain VAD adaptation

**Files:**
- Modify: `audio/recorder.py`
- Modify: `audio/vad.py`
- Modify: `ui/main_window.py`
- Modify: `pipeline.py`
- Test: `tests/test_core.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_window.py`

- [ ] **Step 1: Write failing tests for typed capture results**

Add tests that require this public value from `audio.recorder`:

```python
@dataclass(frozen=True)
class RecordingResult:
    samples: np.ndarray
    stop_reason: Literal["silence", "ptt_release", "timeout", "cancelled"]
    duration_sec: float
```

Cover all four stop reasons without opening a real audio device by mocking the sound stream and stop predicates. Require `duration_sec >= 0` and a mono `float32` sample array.

Run:

```powershell
pytest tests/test_core.py -q
```

Expected: failure because `RecordingResult` and stop reasons do not exist.

- [ ] **Step 2: Return `RecordingResult` from `Recorder.record`**

Track the exact branch that ends capture. Keep the 60-second safety timeout. Convert the captured frames and optional denoise result exactly once, then return the typed result.

Do not silently map cancellation to empty speech; cancellation must remain distinguishable from silence.

- [ ] **Step 3: Write a failing test for cross-turn noise-floor retention**

Expose a read-only property on `VoiceDetector`:

```python
@property
def noise_floor(self) -> float:
    return self._noise_floor
```

Test that `Recorder` initializes the next detector with the final noise floor from the previous completed automatic turn.

Run:

```powershell
pytest tests/test_core.py -q
```

Expected: failure because the recorder currently leaves its stored floor unchanged.

- [ ] **Step 4: Persist the adaptive floor and update pipeline callers**

After an automatic capture, copy `detector.noise_floor` back to `Recorder._noise_floor`. In `ConversationWorker`, pass `result.samples` into transcription and handle reasons as follows:

- `cancelled`: exit the worker cleanly;
- `timeout`: continue with the captured audio and show that the maximum duration was reached;
- `silence` or `ptt_release`: proceed normally when samples exist.

Emit a `recording_finished(str, float)` signal and render a compact status such as `Captured 6.2s · silence` for diagnostics. Do not save this status as conversation content.

- [ ] **Step 5: Verify capture behavior**

Run:

```powershell
pytest tests/test_core.py tests/test_pipeline.py tests/test_window.py -q
pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the checkpoint**

```powershell
git add audio/recorder.py audio/vad.py ui/main_window.py pipeline.py tests/test_core.py tests/test_pipeline.py tests/test_window.py
git commit -m "fix: tornar encerramento da gravacao observavel"
```

---

## Task 3: Make turn-taking safe and understandable

**Files:**
- Modify: `utils/config.py`
- Modify: `settings.json`
- Modify: `ui/settings_dialog.py`
- Modify: `ui/main_window.py`
- Modify: `README.md`
- Test: `tests/test_window.py`

- [ ] **Step 1: Write failing UI tests for explicit turn controls**

Require settings controls with stable object names:

```text
inputModeCombo
pausePresetCombo
transcriptReviewCheck
```

The pause presets must persist these exact seconds:

```text
Short = 1.2
Normal = 2.0
Long = 3.0
```

Require push-to-talk to be the default for a fresh configuration and verify that existing user settings are not overwritten.

Run:

```powershell
pytest tests/test_window.py -q
```

Expected: failure because presets and the new default are not implemented.

- [ ] **Step 2: Add the pause presets and safe default**

Set the default `input_mode` in `AppConfig` and the distributed `settings.json` to `ptt`. Change the default silence duration to `2.0` seconds. Map the three UI presets to the exact numeric values above and include a `Custom` state when an existing config has another value.

Keep direct numeric editing available in advanced settings; presets are a convenience, not a second configuration source.

- [ ] **Step 3: Clarify the live interaction state**

In `MainWindow`, use distinct instructions:

- push-to-talk idle: `Hold Space or the microphone button to speak`;
- push-to-talk recording: `Release to send`;
- automatic idle: `Start speaking; Dogen sends after the selected pause`;
- transcript review: `Edit the transcript, then send or retry`.

Make `Retry` discard the pending transcript and audio without updating context, database rows, or progress metrics. Keep the existing five-second auto-send only when transcript review is enabled, and give the user a visible countdown.

- [ ] **Step 4: Document the two modes**

Update `README.md` with a short “Daily practice” section. Recommend push-to-talk for reliability and automatic mode for hands-free practice. Explain the pause presets and transcript review.

- [ ] **Step 5: Verify and commit**

Run:

```powershell
pytest tests/test_window.py tests/test_pipeline.py -q
pytest -q
```

Expected: all tests pass.

```powershell
git add utils/config.py settings.json ui/settings_dialog.py ui/main_window.py README.md tests/test_window.py tests/test_pipeline.py
git commit -m "feat: tornar controle de turnos previsivel"
```

---

## Task 4: Benchmark and tune transcription without guessing

**Files:**
- Create: `scripts/evaluate_transcription.py`
- Modify: `utils/config.py`
- Modify: `settings.json`
- Modify: `audio/recorder.py`
- Modify: `ui/settings_dialog.py`
- Modify: `docs/quality/daily-practice-baseline.md`
- Test: `tests/test_core.py`
- Test: `tests/test_transcription_evaluation.py`

- [ ] **Step 1: Write failing tests for optional noise reduction**

Add `noise_reduction: bool = True` to `AppConfig`. Test that:

- `Recorder` calls `noisereduce.reduce_noise` only when enabled;
- disabled noise reduction returns normalized captured samples without denoising;
- loading an old settings file supplies the default without rewriting the file.

Run:

```powershell
pytest tests/test_core.py -q
```

Expected: failure because the setting does not exist.

- [ ] **Step 2: Implement and expose the switch**

Pass `noise_reduction` explicitly into `Recorder`. Add a checkbox named `noiseReductionCheck` to advanced audio settings. Do not let the recorder read the JSON configuration directly.

- [ ] **Step 3: Write tests for the evaluation script's pure functions**

The script must accept a UTF-8 JSON manifest:

```json
[
  {"audio": "001.wav", "expected": "I would like to practice English"}
]
```

Test these pure functions:

```python
normalize_text(text: str) -> list[str]
word_error_rate(expected: str, actual: str) -> float
summarize(results: list[dict]) -> dict
```

Use a small local Levenshtein implementation in the script; do not add a runtime package solely for this calculation.

Run:

```powershell
pytest tests/test_transcription_evaluation.py -q
```

Expected: failure because the script does not exist.

- [ ] **Step 4: Implement the CLI benchmark**

Support:

```powershell
python scripts/evaluate_transcription.py --manifest local-evaluation/manifest.json --model small.en --output small-clean.evaluation.json
```

The output must contain per-clip expected text, transcript, WER, runtime, and aggregate median WER. Never include raw audio in the JSON. Exit nonzero for missing clips or an invalid manifest.

- [ ] **Step 5: Compare configurations on the same recordings**

Run the manifest with:

- `small.en`, noise reduction on;
- `small.en`, noise reduction off;
- `medium.en`, noise reduction on;
- `medium.en`, noise reduction off.

Measure model load time separately from per-clip transcription time. Choose the configuration with the lowest manual-edit rate that remains acceptable for daily latency. Record the table and decision in `docs/quality/daily-practice-baseline.md`; do not commit generated evaluation JSON.

- [ ] **Step 6: Verify and commit**

Run:

```powershell
pytest tests/test_core.py tests/test_transcription_evaluation.py -q
pytest -q
git status --short
```

Expected: tests pass and private recordings/results are absent from status.

```powershell
git add utils/config.py settings.json audio/recorder.py ui/settings_dialog.py scripts/evaluate_transcription.py docs/quality/daily-practice-baseline.md tests/test_core.py tests/test_transcription_evaluation.py
git commit -m "feat: medir e configurar qualidade da transcricao"
```

---

## Task 5: Add stop and replay for spoken responses

**Files:**
- Modify: `pipeline.py`
- Modify: `ui/main_window.py`
- Modify: `audio/player.py`
- Modify: `nlp/synthesizer.py`
- Modify: `README.md`
- Modify: `docs/quality/daily-practice-baseline.md`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_window.py`

- [ ] **Step 1: Write failing pipeline tests for side-effect-free replay**

Extract a public `ProcessingPipeline.speak` method with the signature `speak(text: str, emit: Callable[[str, object], None], cancelled: Callable[[], bool]) -> None`.

Test that `speak`:

- strips correction and better-phrasing blocks;
- sends clean sentences to the existing synthesizer/player sequence;
- stops between chunks when cancelled;
- does not call the LLM, append context, or write to the database.

Run:

```powershell
pytest tests/test_pipeline.py -q
```

Expected: failure because response speech is embedded inside `run`.

- [ ] **Step 2: Refactor normal narration through `speak`**

Keep the current sentence streaming and cache behavior. `run` must call the same clean-speech path used by replay. Preserve barge-in cancellation and ensure a partial response is never committed as a complete turn.

- [ ] **Step 3: Write failing UI tests for replay state**

Add buttons with object names `stopAudioButton` and `replayResponseButton`. Require:

- replay disabled before the first complete assistant response;
- replay enabled after a complete response;
- replay disabled while recording, transcribing, or waiting for the LLM;
- stop cancels current playback without ending the session;
- replay does not add a message or increment turn count.

Run:

```powershell
pytest tests/test_window.py -q
```

Expected: failure because the actions do not exist.

- [ ] **Step 4: Implement a dedicated replay worker**

Store only `last_assistant_text` in `MainWindow`. A `ReplayWorker` calls `pipeline.speak`; it must not duplicate Ollama context or database access. Reuse the current cancellation primitive and wait for the worker to finish before starting a second replay.

If synthesis fails, leave the text visible and show `Could not play this response` without disabling the next conversation turn.

- [ ] **Step 5: Compare available local voices**

Using five fixed English sentences, measure LJSpeech and each already-configured local voice for:

- model startup time;
- time to first audio;
- total synthesis time;
- intelligibility;
- subjective naturalness.

Document the selected default and the test machine in `docs/quality/daily-practice-baseline.md`. Do not add another model dependency unless it wins the comparison and its license and disk cost are documented in `README.md`.

- [ ] **Step 6: Verify and commit**

Run:

```powershell
pytest tests/test_pipeline.py tests/test_window.py -q
pytest -q
```

Expected: all tests pass.

```powershell
git add pipeline.py ui/main_window.py audio/player.py nlp/synthesizer.py README.md docs/quality/daily-practice-baseline.md tests/test_pipeline.py tests/test_window.py
git commit -m "feat: adicionar controle e replay da narracao"
```

---

## Task 6: Separate conversation from coaching feedback

**Files:**
- Create: `nlp/feedback.py`
- Modify: `nlp/llm.py`
- Modify: `pipeline.py`
- Modify: `ui/main_window.py`
- Modify: `storage/db.py`
- Test: `tests/test_feedback.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing parser tests**

Define:

```python
FeedbackCategory = Literal[
    "grammar",
    "vocabulary",
    "word_order",
    "verb_tense",
    "agreement",
    "preposition",
    "natural_phrasing",
]

@dataclass(frozen=True)
class CoachFeedback:
    correction: str | None = None
    better_phrasing: str | None = None
    category: FeedbackCategory | None = None

@dataclass(frozen=True)
class ParsedReply:
    message: str
    feedback: CoachFeedback
```

Test `parse_reply(text: str) -> ParsedReply` with:

- reply only;
- correction only;
- better phrasing only;
- both feedback blocks;
- supported category;
- missing or unknown category;
- malformed and multiline blocks.

Unknown or malformed metadata must remain harmless visible text or be ignored conservatively; it must never crash a turn.

Run:

```powershell
pytest tests/test_feedback.py -q
```

Expected: failure because the module does not exist.

- [ ] **Step 2: Implement the parser and one prompt contract**

Move all coaching-tag parsing out of `pipeline.py` and `storage/db.py` into `nlp/feedback.py`. Update the LLM prompt to allow this compact suffix:

```text
[Correction: original → corrected]
[Better phrasing: improved sentence]
[Category: verb_tense]
```

The conversational message remains one short paragraph. The category is emitted only when correction or better phrasing exists. Include two few-shot examples because the local model follows examples more reliably than long rules.

- [ ] **Step 3: Return a typed turn result**

Define in `pipeline.py`:

```python
@dataclass(frozen=True)
class TurnResult:
    transcript: str
    reply: str
    feedback: CoachFeedback
```

Change `ProcessingPipeline.run` to return `TurnResult`. Commit only `reply` to dialogue context. Send only `reply` to `speak`. Render feedback in a separate UI card below the assistant response.

- [ ] **Step 4: Add additive feedback storage**

Create through `Database._init_schema`:

```sql
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    correction TEXT,
    better_phrasing TEXT,
    category TEXT
)
```

Add `save_feedback(session_id: str, feedback: CoachFeedback) -> None`. Do not write an empty feedback row. Keep reading legacy correction tags from old conversation rows for backward-compatible summaries, but all new writes use the new table.

- [ ] **Step 5: Verify separation end to end**

Run:

```powershell
pytest tests/test_feedback.py tests/test_pipeline.py tests/test_core.py tests/test_window.py -q
pytest -q
```

Expected: all tests pass; a test spy proves correction text never reaches the synthesizer.

- [ ] **Step 6: Commit the checkpoint**

```powershell
git add nlp/feedback.py nlp/llm.py pipeline.py ui/main_window.py storage/db.py tests/test_feedback.py tests/test_pipeline.py tests/test_core.py tests/test_window.py
git commit -m "feat: separar conversa e feedback pedagogico"
```

---

## Task 7: Persist objective turn metrics

**Files:**
- Modify: `storage/db.py`
- Modify: `pipeline.py`
- Modify: `ui/main_window.py`
- Modify: `nlp/filler_words.py`
- Test: `tests/test_core.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing schema and persistence tests**

Define:

```python
@dataclass(frozen=True)
class TurnMetrics:
    word_count: int
    filler_count: int
    transcript_edited: bool
    correction_category: str | None
```

Require an additive table:

```sql
CREATE TABLE IF NOT EXISTS turn_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    word_count INTEGER NOT NULL,
    filler_count INTEGER NOT NULL,
    transcript_edited INTEGER NOT NULL,
    correction_category TEXT
)
```

Test zero values, edited transcripts, supported categories, old databases, and cancellation before completion.

Run:

```powershell
pytest tests/test_core.py tests/test_pipeline.py -q
```

Expected: failure because per-turn metrics are not persisted.

- [ ] **Step 2: Calculate metrics once after a successful turn**

Expose a pure filler count function from `nlp/filler_words.py`. Compare the reviewed transcript with the original transcription after whitespace normalization to set `transcript_edited`. Build `TurnMetrics` only after the reply completes successfully.

Persist the conversation, feedback, and metrics in one SQLite transaction. A cancelled recording, retried transcript, failed LLM request, or interrupted partial answer must write none of those three records.

- [ ] **Step 3: Keep existing session summary compatible**

Read new correction totals from `feedback`, falling back to legacy tags for sessions created before this migration. Read filler totals from `turn_metrics`, while retaining the in-memory live count until the new row is committed.

- [ ] **Step 4: Verify and commit**

Run:

```powershell
pytest tests/test_core.py tests/test_pipeline.py tests/test_filler_words.py -q
pytest -q
```

Expected: all tests pass.

```powershell
git add storage/db.py pipeline.py ui/main_window.py nlp/filler_words.py tests/test_core.py tests/test_pipeline.py tests/test_filler_words.py
git commit -m "feat: persistir metricas objetivas por turno"
```

---

## Task 8: Add a useful weekly progress view

**Files:**
- Create: `storage/progress.py`
- Create: `ui/progress_dialog.py`
- Modify: `storage/db.py`
- Modify: `ui/main_window.py`
- Modify: `README.md`
- Test: `tests/test_progress.py`
- Test: `tests/test_window.py`

- [ ] **Step 1: Write failing aggregate tests**

Define:

```python
@dataclass(frozen=True)
class ProgressStats:
    period_days: int
    practiced_days: int
    current_streak: int
    minutes_practiced: float
    completed_turns: int
    words_spoken: int
    fillers_per_100_words: float | None
    transcript_edit_rate: float | None
    corrections_by_category: dict[str, int]
    vocabulary_count: int
```

Test empty data, one day, gaps in a streak, a streak crossing a month boundary, legacy sessions without metrics, zero spoken words, and 7-day versus 30-day windows. Use injected dates in tests; do not depend on the machine clock.

Run:

```powershell
pytest tests/test_progress.py -q
```

Expected: failure because the progress query layer does not exist.

- [ ] **Step 2: Implement progress queries outside the UI**

`storage/progress.py` accepts a `Database` dependency and a `today: date` argument. Use SQLite aggregates for raw totals and small Python functions for streak calculation. Return `None` for rates whose denominator is zero.

Do not construct labels or colors in the storage layer.

- [ ] **Step 3: Write failing UI tests for honest empty states**

Require a `Progress` action in the main window and a dialog that supports 7-day and 30-day views. Test these exact semantic states:

- no completed turns: `Complete your first conversation to see progress`;
- only one practiced day: show totals but no improvement claim;
- fewer than three practiced days: `More practice days are needed for a trend`;
- sufficient data: show current period values and category counts.

Run:

```powershell
pytest tests/test_window.py -q
```

Expected: failure because the dialog does not exist.

- [ ] **Step 4: Implement the progress dialog**

Use simple cards and a category table; do not add a charting dependency. Present:

- current streak and practiced days;
- practice minutes and turns;
- words spoken and filler rate;
- transcript edit rate as a reliability signal, labeled `Transcripts you edited`;
- correction categories;
- vocabulary count.

Explain in a tooltip that these are activity and correction metrics, not a standardized language score.

- [ ] **Step 5: Document the metric definitions**

In `README.md`, state the exact numerator and denominator for filler rate and transcript edit rate, how a practice day is counted, and why pronunciation scoring is absent.

- [ ] **Step 6: Verify and commit**

Run:

```powershell
pytest tests/test_progress.py tests/test_window.py -q
pytest -q
```

Expected: all tests pass.

```powershell
git add storage/progress.py ui/progress_dialog.py storage/db.py ui/main_window.py README.md tests/test_progress.py tests/test_window.py
git commit -m "feat: adicionar progresso local de pratica"
```

---

## Task 9: Run the release-candidate quality gate

**Files:**
- Create: `docs/quality/daily-practice-release-report.md`
- Modify: `docs/quality/daily-practice-baseline.md`
- Modify: `README.md`
- Modify: files implicated by verified defects only
- Test: full suite plus manual protocol

- [ ] **Step 1: Run automated verification from a clean process**

Run:

```powershell
pytest -q
python -m compileall audio nlp storage ui utils pipeline.py main.py
```

Expected: zero failures and zero compilation errors.

- [ ] **Step 2: Repeat the baseline protocol**

Use the same microphone, room conditions, utterances, and measurements from Task 1. Record the release-candidate aggregates beside the baseline. Verify:

- push-to-talk: 0 premature cuts in 20 natural attempts;
- automatic mode: at most 2 premature cuts in 20 natural attempts;
- manual transcript edits reduced by at least 30%, or the retained configuration is explicitly justified;
- stop and replay do not add turns;
- coaching text is not spoken;
- ten consecutive conversations finish without a crash.

- [ ] **Step 3: Dogfood for seven real days**

Complete at least one 15-minute session on seven days. For every defect, capture reproduction steps, operating mode, stop reason, and whether the application recovered. Fix only release-blocking defects:

- data loss;
- unrecoverable UI state;
- repeatable premature capture in push-to-talk;
- response narration that cannot be stopped;
- progress values contradicted by stored rows.

Run focused tests before each fix, then the full suite after it.

- [ ] **Step 4: Write the release report**

`docs/quality/daily-practice-release-report.md` must include:

- machine and microphone used;
- selected Whisper, VAD, denoise, and TTS settings;
- before/after acceptance table;
- automated test command and result;
- known limitations;
- deferred items: pitch-preserving speed control and validated pronunciation assessment.

- [ ] **Step 5: Final repository checks**

Run:

```powershell
pytest -q
git diff --check
git status --short
```

Expected: tests pass, no whitespace errors, no private evaluation files or unrelated changes are staged.

- [ ] **Step 6: Commit the release checkpoint**

```powershell
git add docs/quality/daily-practice-release-report.md docs/quality/daily-practice-baseline.md README.md
git commit -m "docs: validar dogen para pratica diaria"
```

If verified release defects required source changes, stage their exact source and test paths individually before this commit. Confirm the staged list with `git diff --cached --name-only`; do not use `git add .`.

Do not push or publish without explicit user authorization.

---

## Completion checklist

- [ ] All nine task commits exist locally and contain only their own checkpoint.
- [ ] `pytest -q` passes from the Dogen repository root.
- [ ] `git diff --check` reports no errors.
- [ ] The private evaluation corpus remains ignored and untracked.
- [ ] Every acceptance criterion in the design has evidence in the release report.
- [ ] README architecture matches the implemented boundaries.
- [ ] No metric is labeled as pronunciation, fluency, or proficiency unless it directly measures that construct.
- [ ] The Dogen submodule pointer is updated in the harness only after the Dogen commits are complete.
