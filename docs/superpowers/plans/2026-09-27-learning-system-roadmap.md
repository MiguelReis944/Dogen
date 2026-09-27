# Dogen Learning System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Dogen from an open-ended conversation partner into an offline learning system with diagnosis, guided progression, active correction, retention practice, speech/listening work, and portable learner data.

**Architecture:** Add a `learning/` domain layer between the existing conversation pipeline and SQLite/UI. Deterministic services own assessment, curriculum, review scheduling, timing, and mastery; the LLM may generate conversational content but never decides scores or persistence rules. Deliver five usable releases so every checkpoint can be dogfooded before the next subsystem begins.

**Tech Stack:** Python 3.10, PyQt5, SQLite, pytest, Whisper, Coqui TTS, Ollama; standard library for scheduling, JSON backup, and timing.

**Spec:** `docs/design/2026-09-27-learning-system-design.md`

## Global Constraints

- Preserve offline operation and the existing click-to-record conversation path.
- Keep free conversation available in every release.
- Do not display unvalidated pronunciation, fluency, or proficiency scores.
- Audio retention is opt-in; deleting an attempt removes its file and database row.
- Schema changes are additive and migrate existing `conversations.db` files in place.
- Each task follows RED → GREEN → REFACTOR and ends in a local Dogen commit.
- Run the full suite with `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` before every checkpoint.
- Never commit personal recordings, generated databases, caches, or evaluation reports.

## File structure

Create these focused units rather than expanding `ui/main_window.py` or `storage/db.py` further:

```text
learning/
  models.py          domain dataclasses and enums
  profile.py         learner preferences and onboarding state
  diagnostic.py      baseline assessment and per-skill CEFR evidence
  curriculum.py      objective catalog and prerequisites
  planner.py         Today recommendation and guided-session assembly
  session.py         guided-session state machine
  review.py          deterministic spaced-repetition scheduling
  mastery.py         performance and retention aggregation
  timing.py          active-practice intervals
  listening.py       listening exercise generation and grading contracts
  pronunciation.py   audio evidence and validated-assessor boundary
storage/
  learning_repository.py  SQLite reads/writes for learning domain
  backup.py               versioned JSON export/import
ui/
  onboarding_dialog.py
  today_panel.py
  diagnostic_dialog.py
  guided_session_panel.py
  review_dialog.py
  audio_attempt_dialog.py
  listening_dialog.py
  learning_progress_dialog.py
  backup_dialog.py
```

---

## Release 1 — Direction and honest measurement

### Task 1: Learning schema and repository

**Covers:** learner profile foundation, goals, CEFR evidence, future multi-profile boundary.

**Files:**
- Create: `learning/__init__.py`
- Create: `learning/models.py`
- Create: `storage/learning_repository.py`
- Modify: `storage/db.py`
- Test: `tests/test_learning_repository.py`

**Interfaces:**
- Produces: `LearnerProfile`, `Skill`, `CefrBand`, `LearningObjective`, `Evidence`, `LearningRepository`.
- `LearningRepository.profile() -> LearnerProfile | None`
- `LearningRepository.save_profile(profile: LearnerProfile) -> None`
- `LearningRepository.add_evidence(evidence: Evidence) -> int`
- `LearningRepository.evidence_for(skill: Skill) -> list[Evidence]`

- [ ] **Step 1: Write failing migration and round-trip tests**

```python
def test_profile_and_evidence_survive_database_reopen(tmp_path):
    profile = LearnerProfile("default", "pt-BR", "conversation", 15, "after_turn")
    evidence = Evidence("default", Skill.SPEAKING, CefrBand.A2, "diagnostic", True, 0.8)
    with Database(tmp_path / "dogen.db") as db:
        repo = LearningRepository(db.connection)
        repo.save_profile(profile)
        repo.add_evidence(evidence)
    with Database(tmp_path / "dogen.db") as db:
        repo = LearningRepository(db.connection)
        assert repo.profile() == profile
        assert repo.evidence_for(Skill.SPEAKING) == [evidence]
```

- [ ] **Step 2: Run the focused test and verify the missing tables/types failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_learning_repository.py -q -p no:cacheprovider`

- [ ] **Step 3: Implement immutable domain types and additive tables**

Use string enums for `Skill` and `CefrBand`. Add `learner_profile`, `learning_objectives`, `learning_evidence`, and indexes in `Database.init_schema()`. Repository methods must use transactions and explicit column lists.

- [ ] **Step 4: Reopen an existing pre-learning database fixture and verify no conversation rows change**

- [ ] **Step 5: Run the full suite and commit**

```powershell
git add learning storage tests/test_learning_repository.py
git commit -m "feat: adicionar dominio de aprendizagem"
```

### Task 2: Onboarding and learner goals

**Covers:** no onboarding, no goals, fixed correction behavior.

**Files:**
- Create: `learning/profile.py`
- Create: `ui/onboarding_dialog.py`
- Modify: `main.py`
- Modify: `ui/settings_dialog.py`
- Test: `tests/test_onboarding.py`

**Interfaces:**
- Consumes: `LearningRepository.save_profile()` from Task 1.
- Produces: `ProfileService.needs_onboarding() -> bool`, `ProfileService.complete(OnboardingAnswers) -> LearnerProfile`.

- [ ] **Step 1: Write failing tests for first-run and returning-user behavior**

```python
def test_onboarding_is_required_once(repository):
    service = ProfileService(repository)
    assert service.needs_onboarding()
    service.complete(OnboardingAnswers("pt-BR", "travel", 15, "after_turn"))
    assert not service.needs_onboarding()
```

- [ ] **Step 2: Verify the test fails because `ProfileService` is absent**

- [ ] **Step 3: Implement the service and a dialog for native language, goal, daily minutes, and correction timing**

Correction timing values are exactly `immediate`, `after_turn`, and `session_end`. Settings edits the same profile fields instead of duplicating JSON configuration.

- [ ] **Step 4: Wire `main.py` to show onboarding before `MainWindow` and persist only on acceptance**

- [ ] **Step 5: Run onboarding tests, the full suite, and commit**

```powershell
git add learning/profile.py ui/onboarding_dialog.py ui/settings_dialog.py main.py tests/test_onboarding.py
git commit -m "feat: adicionar onboarding do aluno"
```

### Task 3: Diagnostic baseline and per-skill level evidence

**Covers:** no initial diagnosis, no CEFR progression.

**Files:**
- Create: `learning/diagnostic.py`
- Create: `ui/diagnostic_dialog.py`
- Create: `tests/fixtures/diagnostic_items.json`
- Test: `tests/test_diagnostic.py`

**Interfaces:**
- Produces: `DiagnosticItem`, `DiagnosticAttempt`, `DiagnosticResult`.
- `DiagnosticService.next_item(state) -> DiagnosticItem | None`
- `DiagnosticService.grade(item, answer) -> DiagnosticAttempt`
- `DiagnosticService.result(attempts) -> DiagnosticResult`

- [ ] **Step 1: Write failing deterministic grading tests**

```python
def test_diagnostic_reports_separate_skill_bands():
    attempts = [
        DiagnosticAttempt("grammar-a2-1", Skill.GRAMMAR, True),
        DiagnosticAttempt("listen-a1-1", Skill.LISTENING, False),
    ]
    result = DiagnosticService(catalog()).result(attempts)
    assert result.band_for(Skill.GRAMMAR) == CefrBand.A2
    assert result.band_for(Skill.LISTENING) == CefrBand.A1
```

- [ ] **Step 2: Verify RED and implement a versioned local diagnostic catalog**

The first catalog contains 18 hand-authored items: grammar, vocabulary, listening, and speaking prompts across A1–B1. Do not infer levels from an unconstrained conversation.

- [ ] **Step 3: Persist each attempt as evidence and permit “skip for now” without inventing a level**

- [ ] **Step 4: Build the dialog with progress, replay for listening items, and a plain-language result breakdown**

- [ ] **Step 5: Run tests and commit**

```powershell
git add learning/diagnostic.py ui/diagnostic_dialog.py tests/fixtures/diagnostic_items.json tests/test_diagnostic.py
git commit -m "feat: adicionar diagnostico inicial"
```

### Task 4: Active-practice timer and evidence-based progress

**Covers:** inaccurate time, activity-only metrics.

**Files:**
- Create: `learning/timing.py`
- Create: `learning/mastery.py`
- Modify: `storage/progress.py`
- Modify: `ui/progress_dialog.py`
- Modify: `ui/main_window.py`
- Test: `tests/test_learning_progress.py`

**Interfaces:**
- `PracticeTimer.start(now)`, `pause(now)`, `resume(now)`, `finish(now) -> int` seconds.
- `MasteryService.summary(profile_id) -> MasterySummary` with activity, performance, retention, and reliability sections.

- [ ] **Step 1: Write failing timer tests using fixed datetimes**

```python
def test_timer_excludes_idle_gap():
    timer = PracticeTimer()
    timer.start(at(10, 0)); timer.pause(at(10, 5))
    timer.resume(at(10, 20)); timer.finish(at(10, 25))
    assert timer.active_seconds == 600
```

- [ ] **Step 2: Write a failing progress test proving ten turns do not imply mastery**

- [ ] **Step 3: Implement timing events and persist active seconds per session**

- [ ] **Step 4: Split the Progress UI into Activity, Performance, Retention, and Recognition reliability**

- [ ] **Step 5: Run tests and commit**

```powershell
git add learning/timing.py learning/mastery.py storage ui tests/test_learning_progress.py
git commit -m "feat: medir pratica e aprendizagem separadamente"
```

---

## Release 2 — Teaching loop

### Task 5: Curriculum catalog and Today planner

**Covers:** no curriculum, no learning plan, weak habit direction.

**Files:**
- Create: `learning/curriculum.py`
- Create: `learning/planner.py`
- Create: `learning/catalog/a1_b1.json`
- Create: `ui/today_panel.py`
- Modify: `ui/main_window.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- `Curriculum.objectives_for(skill, band) -> list[LearningObjective]`
- `Planner.recommend(profile, evidence, due_reviews, today) -> TodayPlan`
- `TodayPlan.reason` is required and user-visible.

- [ ] **Step 1: Write failing priority tests**

```python
def test_due_review_precedes_new_objective():
    plan = planner.recommend(profile, weak_grammar_evidence, [overdue_review], today)
    assert plan.primary.kind == "review"
    assert "due" in plan.reason.lower()
```

- [ ] **Step 2: Implement a small catalog of 24 objectives with explicit prerequisites**

- [ ] **Step 3: Implement deterministic priority: overdue review, weak prerequisite, current goal, then new objective**

- [ ] **Step 4: Add the Today panel with Start guided session and Free conversation choices**

- [ ] **Step 5: Run tests and commit**

```powershell
git add learning/curriculum.py learning/planner.py learning/catalog ui/today_panel.py tests/test_planner.py ui/main_window.py
git commit -m "feat: recomendar pratica diaria"
```

### Task 6: Guided-session state machine and measurable scenarios

**Covers:** unstructured sessions, scenarios without outcomes.

**Files:**
- Create: `learning/session.py`
- Create: `ui/guided_session_panel.py`
- Modify: `nlp/llm.py`
- Modify: `pipeline.py`
- Test: `tests/test_guided_session.py`

**Interfaces:**
- `GuidedSession.advance(event) -> SessionStage`
- Stages: `WARMUP`, `GUIDED_PRACTICE`, `CHALLENGE`, `REVIEW`, `COMPLETE`.
- `ScenarioTemplate` requires `objective_id`, `success_rule`, and `target_language`.

- [ ] **Step 1: Write failing transition tests, including retry and cancellation**

```python
def test_challenge_requires_independent_evidence_before_completion():
    session = guided_session_for("past-events-a2")
    session.advance(WarmupDone()); session.advance(GuidedPracticeDone())
    assert session.stage is SessionStage.CHALLENGE
    assert session.advance(ChallengeScored(False)) is SessionStage.CHALLENGE
    assert session.advance(ChallengeScored(True)) is SessionStage.REVIEW
```

- [ ] **Step 2: Implement the state machine without Qt or LLM dependencies**

- [ ] **Step 3: Replace free-form scenario strings with templates that feed the prompt and deterministic success evaluator**

- [ ] **Step 4: Render the objective and current stage without hiding the conversation**

- [ ] **Step 5: Run tests and commit**

```powershell
git add learning/session.py ui/guided_session_panel.py nlp/llm.py pipeline.py tests/test_guided_session.py
git commit -m "feat: adicionar sessoes guiadas"
```

### Task 7: Active corrections and learner-controlled timing

**Covers:** passive correction, no correction timing choice.

**Files:**
- Create: `learning/correction.py`
- Modify: `nlp/feedback.py`
- Modify: `ui/main_window.py`
- Modify: `storage/learning_repository.py`
- Test: `tests/test_correction_practice.py`

**Interfaces:**
- `CorrectionPractice.from_feedback(feedback) -> CorrectionPractice | None`
- `CorrectionPractice.grade_retry(transcript) -> RetryResult`
- A correction is `learned=False` until a successful retry and delayed review exist.

- [ ] **Step 1: Write failing tests for exact retry, transfer retry, and skipped correction**

- [ ] **Step 2: Implement normalized deterministic matching for constrained retry prompts**

- [ ] **Step 3: Queue corrections according to `immediate`, `after_turn`, or `session_end` profile preference**

- [ ] **Step 4: Add Retry and Explain actions to the Fixes panel; Explain may use the LLM, but grading may not**

- [ ] **Step 5: Persist attempts, run tests, and commit**

```powershell
git add learning/correction.py nlp/feedback.py ui/main_window.py storage/learning_repository.py tests/test_correction_practice.py
git commit -m "feat: tornar correcoes praticaveis"
```

---

## Release 3 — Memory and adaptation

### Task 8: Vocabulary learning items and spaced repetition

**Covers:** weak vocabulary tracker, no spaced repetition, no retention measurement.

**Files:**
- Create: `learning/review.py`
- Replace: `ui/vocab_dialog.py` with `ui/review_dialog.py`
- Modify: `storage/learning_repository.py`
- Modify: `storage/models.py`
- Test: `tests/test_review_scheduler.py`

**Interfaces:**
- `ReviewScheduler.grade(item, grade, reviewed_at) -> ReviewItem`.
- Grades: `AGAIN`, `HARD`, `GOOD`, `EASY`.
- `LearningRepository.due_reviews(profile_id, now, limit) -> list[ReviewItem]`.

- [ ] **Step 1: Write failing interval tests with literal expected dates**

```python
def test_again_returns_item_to_same_day():
    updated = ReviewScheduler().grade(new_item(), ReviewGrade.AGAIN, date(2026, 9, 27))
    assert updated.due_on == date(2026, 9, 27)
    assert updated.lapses == 1
```

- [ ] **Step 2: Implement deterministic intervals and version the algorithm on each item**

- [ ] **Step 3: Migrate correction pairs into review items without deleting the legacy `vocab` table**

- [ ] **Step 4: Build recognition and production review cards with definition, example, audio, and grade buttons**

- [ ] **Step 5: Record delayed success as retention evidence, run tests, and commit**

```powershell
git add learning/review.py ui/review_dialog.py storage tests/test_review_scheduler.py
git commit -m "feat: adicionar revisao espacada"
```

### Task 9: Recurring-error patterns and adaptive planner input

**Covers:** no adaptation to recurring errors, no mastery model.

**Files:**
- Create: `learning/errors.py`
- Modify: `learning/mastery.py`
- Modify: `learning/planner.py`
- Modify: `storage/learning_repository.py`
- Test: `tests/test_error_patterns.py`

**Interfaces:**
- `ErrorPatternService.record(correction_attempt) -> ErrorPattern`.
- `ErrorPatternService.priority_patterns(profile_id) -> list[ErrorPattern]`.
- A pattern requires at least two independent occurrences; one correction is not a weakness.

- [ ] **Step 1: Write failing tests proving one error does not create a priority and repeated errors do**

- [ ] **Step 2: Implement pattern keys from correction category plus normalized corrected construction**

- [ ] **Step 3: Feed due high-priority patterns into `Planner.recommend()`**

- [ ] **Step 4: Show evidence count, last occurrence, and next scheduled practice in Progress**

- [ ] **Step 5: Run tests and commit**

```powershell
git add learning/errors.py learning/mastery.py learning/planner.py storage/learning_repository.py tests/test_error_patterns.py
git commit -m "feat: adaptar pratica a erros recorrentes"
```

---

## Release 4 — Speech and listening

### Task 10: Optional audio history and self-comparison

**Covers:** no self-replay, foundation for pronunciation work.

**Files:**
- Create: `audio/archive.py`
- Create: `learning/pronunciation.py`
- Create: `ui/audio_attempt_dialog.py`
- Modify: `audio/recorder.py`
- Modify: `ui/settings_dialog.py`
- Test: `tests/test_audio_archive.py`

**Interfaces:**
- `AudioArchive.save(profile_id, samples, sample_rate, purpose) -> AudioAttempt`.
- `AudioArchive.delete(attempt_id) -> None` removes row and file atomically where possible.
- `PronunciationAssessor` returns evidence labels, never a percentage, until its benchmark is approved.

- [ ] **Step 1: Write failing opt-in, save, playback-path, and delete tests using temporary WAV files**

- [ ] **Step 2: Implement an app-owned `user-data/audio/` directory and UUID filenames**

- [ ] **Step 3: Add “Keep my recordings for review” disabled by default**

- [ ] **Step 4: Add Listen to mine, Listen to reference, Try again, and Delete controls**

- [ ] **Step 5: Create `docs/quality/pronunciation-validation.md` with a 100-attempt benchmark gate before phoneme scoring**

- [ ] **Step 6: Run tests and commit**

```powershell
git add audio/archive.py learning/pronunciation.py ui/audio_attempt_dialog.py ui/settings_dialog.py tests/test_audio_archive.py docs/quality/pronunciation-validation.md
git commit -m "feat: adicionar revisao da propria voz"
```

### Task 11: Listening exercises and controlled auditory variety

**Covers:** weak listening practice, one speed/voice/accent.

**Files:**
- Create: `learning/listening.py`
- Create: `ui/listening_dialog.py`
- Create: `scripts/validate_voices.py`
- Modify: `nlp/synthesizer.py`
- Modify: `learning/planner.py`
- Test: `tests/test_listening.py`

**Interfaces:**
- `ListeningExercise` stores transcript, question, accepted answers, band, voice variant, and speech rate.
- `ListeningService.grade(exercise, answer) -> ListeningResult` uses accepted answers, not an LLM judgment.
- Only voices passing the local startup and intelligibility fixture enter the selectable catalog.

- [ ] **Step 1: Write failing grading, replay-limit, and transcript-reveal tests**

- [ ] **Step 2: Implement hand-authored A1–B1 gist/detail items and deterministic grading**

- [ ] **Step 3: Add speech-rate control at 0.8×, 1.0×, and 1.15× with pitch-preserving output or omit unsupported rates**

- [ ] **Step 4: Add a voice catalog validation script and expose only variants that pass it**

- [ ] **Step 5: Feed listening weakness into Today planning, run tests, and commit**

```powershell
git add learning/listening.py ui/listening_dialog.py nlp/synthesizer.py learning/planner.py tests/test_listening.py scripts/validate_voices.py
git commit -m "feat: adicionar pratica de listening"
```

---

## Release 5 — Daily product and portability

### Task 12: Daily target, resume flow, first-run diagnostics, and backup

**Covers:** weak habit loop, fragile installation, fragile data portability.

**Files:**
- Create: `learning/habit.py`
- Create: `storage/backup.py`
- Create: `ui/backup_dialog.py`
- Create: `ui/reminder_dialog.py`
- Modify: `scripts/preflight.py`
- Modify: `ui/today_panel.py`
- Modify: `ui/main_window.py`
- Test: `tests/test_habit.py`
- Test: `tests/test_backup.py`
- Test: `tests/test_preflight.py`

**Interfaces:**
- `HabitService.today(profile_id, date) -> DailyStatus`.
- `HabitService.reminder_due(profile_id, now) -> bool` returns true at most once per local day when the target is incomplete.
- `BackupService.export(path) -> BackupManifest`.
- `BackupService.import_file(path, strategy="replace") -> ImportReport`.
- Backup format has integer `schema_version`, SHA-256 checksums, and contains no audio unless explicitly requested.

- [ ] **Step 1: Write failing daily-target tests that count active minutes and retained reviews, not app-open time**

- [ ] **Step 2: Write failing backup round-trip and corrupted-checksum tests**

- [ ] **Step 3: Extend preflight to report microphone, Ollama, selected model, Whisper cache, TTS cache, and writable data directory with one action per failure**

- [ ] **Step 4: Implement Today resume text from the last incomplete guided session and next due review**

- [ ] **Step 5: Show one dismissible in-app daily reminder when the target is incomplete; never create an operating-system background task**

- [ ] **Step 6: Implement versioned export/import with a preview before replacement and an automatic pre-import backup**

- [ ] **Step 7: Add File → Backup and File → Restore actions, run tests, and commit**

```powershell
git add learning/habit.py storage/backup.py ui/backup_dialog.py ui/reminder_dialog.py scripts/preflight.py ui/today_panel.py ui/main_window.py tests
git commit -m "feat: concluir experiencia diaria offline"
```

### Task 13: Seven-day product acceptance

**Covers:** validates all 20 improvements as a coherent product rather than isolated features.

**Files:**
- Create: `docs/quality/learning-system-acceptance.md`
- Create: `scripts/export_acceptance_metrics.py`
- Test: `tests/test_acceptance_export.py`

**Interfaces:**
- Export contains aggregate counts only; no conversation text or audio.

- [ ] **Step 1: Write a failing privacy test proving exported acceptance metrics contain no transcript, path, or audio filename**

- [ ] **Step 2: Implement the aggregate exporter**

- [ ] **Step 3: Run a scripted smoke test covering onboarding → diagnostic → Today → guided session → correction retry → review → backup/restore**

- [ ] **Step 4: Dogfood for seven days with at least five guided sessions, ten delayed reviews, three listening activities, and five self-replay attempts**

- [ ] **Step 5: Record observed failures, retention results, startup failures, and abandoned flows in the acceptance document**

- [ ] **Step 6: Mark the learning-system release candidate only if backup restore succeeds and no Critical issue remains**

```powershell
git add docs/quality/learning-system-acceptance.md scripts/export_acceptance_metrics.py tests/test_acceptance_export.py
git commit -m "docs: validar sistema de aprendizagem"
```

## Release gates

Do not start a later release merely because the previous code merged. Pass its product gate first:

| Release | Gate |
|---|---|
| 1 | A fresh user completes onboarding and diagnostic; active time excludes a 15-minute idle gap |
| 2 | Five guided sessions finish with objective evidence; corrections require a retry |
| 3 | Ten items become due and are reviewed later; mastery changes only from evidence |
| 4 | Audio opt-in/delete works; listening grading is deterministic; no fake pronunciation score exists |
| 5 | Fresh-machine preflight is actionable; backup round-trip preserves learning state |

## Scope explicitly deferred

- Cloud accounts, synchronization, subscriptions, social features, and leaderboards.
- A mobile client.
- A global fluency percentage.
- Phoneme scoring before the pronunciation benchmark passes.
- Automatic generation of the full CEFR curriculum before the hand-authored A1–B1 catalog is dogfooded.
