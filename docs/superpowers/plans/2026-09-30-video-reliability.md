# Dogen Video Findings — Reliability Plan

> Approved for implementation by the user on 2026-09-30. Execute incrementally, test-first, and keep each verified checkpoint independently reviewable.

**Goal:** Reproduce and correct the reliability defects demonstrated or reported in the two 2026-09-30 dogfood videos, and make the five approved architectural improvements below without changing Dogen's offline-first product boundaries or inventing new learning scores.

**Architecture:** Keep the existing PyQt worker, audio pipeline, SQLite store, local Whisper, Ollama, and Coqui TTS. Trace each affected value across its current component boundaries, add a regression test for the reproduced failure, and make the smallest change at the point where data is lost or misreported.

**Tech Stack:** Python 3.10+, PyQt5, NumPy, sounddevice, Whisper, Ollama, SQLite, pytest.

**Spec:** `docs/prd.md`, `docs/architecture.md`, `docs/design.md`, and `docs/quality/daily-practice-baseline.md`.

## Global Constraints

- Keep the product offline-first; do not send voice, transcripts, or history to a remote service.
- Preserve the user's current `settings.json`, untracked export files, and all private recordings.
- Do not change the default `small.en` model or microphone/VAD sensitivity based on one recognition or cutoff example; use the private benchmark protocol first.
- Keep `New Session` as an intentional conversation-context reset; do not add cross-session personal memory without separate approval.
- Keep corrections distinct from fluency mode and from recognition confidence.
- Preserve current definitions: practice time counts captured microphone audio only; interruptions do not become completed turns.
- Do not claim a fix until focused tests, the full suite, and the relevant manual check pass.
- Prefer a narrow boundary improvement that directly supports a tested behavior; do not refactor a subsystem merely to make it look cleaner.

## Approved architecture improvements

These are incremental quality improvements, not a rewrite. Apply them alongside the relevant behavior checkpoints so each has a measurable reason and regression coverage:

1. Add end-to-end turn-contract tests that exercise capture outcome, processing outcome, persistence, and rendered status/history; use small local trace identifiers where needed to follow a turn across those boundaries.
2. Give Today and Practice Progress a shared source for same-label aggregates and definitions, while preserving their different date ranges.
3. Extract `ConversationWorker` from `ui/main_window.py` only after behavior tests cover its signals and lifecycle, leaving the window responsible for presentation and coordination.
4. Make application/turn lifecycle transitions explicit and test invalid or duplicate transitions rather than relying on loosely coordinated UI booleans.
5. Add opt-in/local privacy-safe diagnostics for reliability failures; record state, durations, stop reason, and error class/message as appropriate, but never audio, transcript contents, API keys, or personal conversation text.

---

### Task 1: Reproduce the recording cutoff and capture stall

**Files:**
- Inspect/modify only if evidence requires: `audio/recorder.py`, `audio/vad.py`, `pipeline.py`, `ui/main_window.py`.
- Extend: `tests/test_core.py`, `tests/test_pipeline.py`, `tests/test_window.py`.
- Record confirmed evidence in: `docs/quality/daily-practice-release-report.md`.

- [ ] Add deterministic recorder tests for click-to-start/click-to-finish, a natural 1–2 second pause, cancellation, and maximum-duration exit. Assert captured sample duration and `stop_reason` separately.
- [ ] Run the focused tests and inspect existing stop-reason/status signals before changing capture logic.
- [ ] Reproduce manually with the user's click-controlled mode and the same phrase/pause pattern reported in the videos; record only mode, duration, stop reason, and whether text was cut. Do not retain audio unless the user explicitly opts in.
- [ ] If capture ends before the finish click, fix only the branch proven to stop it early and add that exact case as a regression test. Do not tune microphone sensitivity as a substitute for a correct stop condition.
- [ ] Run `python -m pytest tests/test_core.py tests/test_pipeline.py tests/test_window.py -q`, then `python -m pytest -q`.

### Task 2: Keep session history and exports consistent

**Files:**
- Inspect/modify only if reproduced: `ui/main_window.py`, `storage/db.py`, `storage/models.py`, `nlp/llm.py`.
- Extend: `tests/test_window.py`, `tests/test_core.py`, and `tests/test_pipeline.py`.

- [ ] Add tests asserting that a completed turn shown in the conversation is present in `Database.session_messages(session_id)` and in an export made after the completion signal.
- [ ] Add a separate interrupted-stream test asserting that the partial assistant text remains visibly marked and exportable but is not added to future LLM context or counted as completed.
- [ ] Trace the visible two-turn/export mismatch from the UI signal through the SQLite write and the export query. Fix the first boundary where a displayed, completed message is missing; do not add a second history store.
- [ ] For an empty current session, show a clear “nothing to export” message and do not silently create a zero-byte export. Keep prior sessions stored and exportable.
- [ ] Verify that `New Session` clears only the active context and UI. Do not carry facts into a new session. If the earlier phrase was lost inside the same session, fix that persistence/context defect; if it crossed a deliberate session reset, report that current behavior is by design and ask before adding long-term memory.
- [ ] Run `python -m pytest tests/test_core.py tests/test_pipeline.py tests/test_window.py -q`, then `python -m pytest -q`.

### Task 3: Reconcile Today and Practice Progress against stored rows

**Files:**
- Inspect/modify only if reproduced: `storage/progress.py`, `storage/db.py`, `ui/main_window.py`.
- Extend: `tests/test_progress.py`, `tests/test_window.py`.

- [ ] Seed one in-memory database with completed, interrupted, and recording-duration rows matching the two video snapshots.
- [ ] Assert Today and Practice Progress use the same stored source for each metric that has the same label; separately assert that captured minutes equal the sum of saved recording frames/durations, not elapsed time between turns.
- [ ] Trace any mismatch to its query, session/date boundary, or refresh signal and correct only that source. Preserve the distinction between attempts, completed turns, words, and microphone-active time.
- [ ] Run `python -m pytest tests/test_progress.py tests/test_window.py -q`, then `python -m pytest -q`.

### Task 4: Verify Fixes and lengthen transcript review

**Files:**
- Inspect/modify only if needed: `nlp/feedback.py`, `pipeline.py`, `storage/db.py`, `ui/main_window.py`.
- Modify: `ui/main_window.py`, `README.md`, and `docs/architecture.md` for the review countdown and its documented behavior.
- Extend: `tests/test_feedback.py`, `tests/test_pipeline.py`, `tests/test_core.py`, `tests/test_window.py`.

- [ ] Add an end-to-end test using a deterministic coaching-mode response with a structured correction. Verify it passes through parsing, storage, and the read-only Fixes view. Add a corresponding Fluency-mode test confirming no correction is fabricated.
- [ ] Reproduce the empty Fixes case with a known learner error while explicitly confirming Coaching mode. If structured feedback exists but is not displayed, repair that UI/storage boundary; if the model emits no structured feedback, do not promise that every error will be corrected and do not mix in an unrequested prompt rewrite.
- [x] Increase transcript auto-send from 5 to 15 seconds, update the visible countdown/status to match, and test auto-send, immediate Enter/send, and Retry/cancel without duplicate turns. Keep the current setting file untouched.
- [x] Run the focused feedback/window tests, then `python -m pytest -q`.

### Task 5: Retest already-landed loading, icon, and empty-state behavior

**Files:**
- No source changes unless a manual regression is confirmed. Candidate tests: `tests/test_window.py`; visual check of `ui/main_window.py`, startup/AppUserModelID behavior, and the Vocabulary dialog.

- [ ] On a fresh launch, confirm File actions expose an explicit loading state and become available after initialization; this behavior is already present in commit `a762317`.
- [ ] Confirm Fixes has a readable empty state when there are no recorded corrections.
- [ ] Confirm the Dogen taskbar icon and Vocabulary table render correctly on the user's Windows desktop. The supplied videos show the Dogen icon and no white Vocabulary bar, so do not rewrite branding or styles unless the defect reproduces.
- [ ] If these checks pass, record them as verified and make no code changes for these items.

### Task 6: Acceptance and evidence

**Files:**
- Update only after verification: `docs/quality/daily-practice-release-report.md`, and `docs/memory.md` only if a durable behavior changes.

- [ ] Run `python -m pytest -q` and `git diff --check` from the Dogen repository.
- [ ] Repeat the 20-utterance push-to-talk portion of `docs/quality/daily-practice-baseline.md`; record stop reason and whether the sentence was cut, not a pronunciation score.
- [ ] Manually verify a coaching correction, transcript review with the 15-second countdown, a completed export, an empty-session export attempt, Today vs. Progress, and one New Session reset.
- [ ] Record only results actually observed. Leave the seven-day dogfood acceptance pending until it is completed.

### Task 7: Shared metric definitions and end-to-end turn trace

**Files:**
- Inspect/modify only where Task 2 or Task 3 demonstrates divergence: `storage/progress.py`, `ui/main_window.py`, and the smallest relevant service boundary.
- Extend: `tests/test_progress.py`, `tests/test_window.py`, and one focused pipeline-to-storage contract test.

- [ ] Define one shared aggregate API for metrics shown in both Today and Practice Progress; keep date-window selection explicit at the caller.
- [ ] Assert same-day Today values equal the corresponding last-7-days Progress values when both see the same seeded local-day rows.
- [ ] Include a per-turn trace/correlation identifier only if it can be kept local and content-free; assert it links stage outcomes without logging transcript or audio data.
- [ ] Run focused tests and the full suite before committing this checkpoint.

### Task 8: Explicit lifecycle states and worker boundary

**Files:**
- `ui/main_window.py`; create `ui/conversation_worker.py` only after coverage shows the current worker contract.
- Extend: `tests/test_window.py` and add focused worker signal/lifecycle tests.

- [ ] Capture legal transitions for startup/loading, ready, recording, processing, interrupted/error, and shutdown.
- [ ] Add tests for duplicate start/stop, shutdown during capture, and recovery to ready/error without disabling File actions indefinitely.
- [ ] Move the worker into its own module without changing signals or behavior; keep UI rendering and action wiring in the window.
- [ ] Run focused tests, full suite, and `git diff --check` before committing.

### Task 9: Privacy-safe local diagnostics

**Files:**
- `ui/main_window.py`, `pipeline.py`, and/or a small diagnostics helper only if the demonstrated failures cannot be diagnosed from existing signals/logs.
- Extend targeted tests to prove sensitive user content is excluded.

- [ ] Record only state transitions, elapsed stage durations, stop reason, and sanitized error metadata needed to reproduce reliability problems.
- [ ] Do not log audio, transcript, LLM response, secrets, or full personal messages; keep diagnostics local and bounded.
- [ ] Add a test that injects a recognizable private phrase and verifies it is absent from diagnostic output.
- [ ] Keep this checkpoint small; if existing diagnostics suffice, document that result and make no code change.

## Execution baseline and observations excluded from code changes unless they regress

- Baseline on the available system Python: `python -m pytest -q -p no:cacheprovider` — 140 passed in 18.79s. The Dogen `.venv` is absent; no packages were installed.
- At implementation start, `settings.json` is pre-existing modified user data and `dogen-session-62b28f04.txt` is a pre-existing untracked export; neither is part of this plan or any commit.

- File loading status, interruption of TTS, Dogen's taskbar identity, configured daily goal, and the empty-Fixes message already have implementations or positive evidence in the current branch; retest before touching them.
- Keep `small.en` for now. The videos show one `upgrade the app` recognition error followed by a correct repeat; the existing 120-utterance private benchmark is the evidence gate for changing models or noise-reduction defaults.
- No external LLM APIs, cloud memory, new UI redesign, vocabulary redesign, or pronunciation/proficiency score is part of this scope.
