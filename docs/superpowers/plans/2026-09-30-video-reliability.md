# Dogen Video Findings — Reliability Plan

> Proposal only. No product code changes are authorized by this plan; wait for the user's approval before implementation.

**Goal:** Reproduce and correct only the reliability defects demonstrated or reported in the two 2026-09-30 dogfood videos, without changing Dogen's offline-first architecture or inventing new learning scores.

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
- Modify: `ui/main_window.py` for the review countdown.
- Extend: `tests/test_feedback.py`, `tests/test_pipeline.py`, `tests/test_core.py`, `tests/test_window.py`.

- [ ] Add an end-to-end test using a deterministic coaching-mode response with a structured correction. Verify it passes through parsing, storage, and the read-only Fixes view. Add a corresponding Fluency-mode test confirming no correction is fabricated.
- [ ] Reproduce the empty Fixes case with a known learner error while explicitly confirming Coaching mode. If structured feedback exists but is not displayed, repair that UI/storage boundary; if the model emits no structured feedback, do not promise that every error will be corrected and do not mix in an unrequested prompt rewrite.
- [ ] Increase transcript auto-send from 5 to 15 seconds, update the visible countdown/status to match, and test auto-send, immediate Enter/send, and Retry/cancel without duplicate turns. Keep the current setting file untouched.
- [ ] Run the focused feedback/window tests, then `python -m pytest -q`.

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

## Current observations excluded from code changes unless they regress

- File loading status, interruption of TTS, Dogen's taskbar identity, configured daily goal, and the empty-Fixes message already have implementations or positive evidence in the current branch; retest before touching them.
- Keep `small.en` for now. The videos show one `upgrade the app` recognition error followed by a correct repeat; the existing 120-utterance private benchmark is the evidence gate for changing models or noise-reduction defaults.
- No external LLM APIs, cloud memory, new UI redesign, vocabulary redesign, or pronunciation/proficiency score is part of this scope.
