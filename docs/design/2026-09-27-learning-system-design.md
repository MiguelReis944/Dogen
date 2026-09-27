# Dogen Learning System Design

## Product outcome

Dogen must evolve from an open-ended conversation partner into a local learning system that can answer three questions with evidence:

1. What should this learner practice today?
2. Why was that activity selected?
3. What later performance shows that the learner retained it?

The product remains offline-first. Conversation is still the main interaction, but every guided session has an objective, produces evidence, and schedules the next useful activity.

## Product principles

- Do not invent pronunciation, fluency, or proficiency scores.
- Separate recognition confidence from language correctness.
- Prefer recall and fresh production over passive reading.
- Keep free conversation available; guided learning must not replace it.
- Store recordings only after explicit opt-in and make deletion immediate.
- Every metric must have a plain-language definition and an observable source.
- Add one learner profile first; multi-profile support may reuse the same data boundary later.

## Core domain

### Learner profile

`LearnerProfile` stores the target language, native language, self-reported goals, preferred correction timing, daily target, current CEFR estimate, and completed onboarding state.

### Skill model

The initial taxonomy is deliberately small:

- speaking: intelligibility, interaction, fluency evidence;
- listening: gist and detail comprehension;
- grammar: tense, agreement, word order, prepositions;
- vocabulary: recognition, recall, and productive use;
- discourse: narration, explanation, persuasion, and repair.

CEFR estimates are recorded per skill with their evidence source. A single global level is a display summary, not the source of truth.

### Learning objective

`LearningObjective` defines one observable behavior, such as “produce five past-tense sentences about a completed event with at most one tense error.” Objectives belong to a CEFR band and skill.

### Guided session

A `LessonPlan` contains:

1. a short warm-up;
2. one explicit objective;
3. guided practice;
4. an independent challenge;
5. recall of due review items;
6. a summary based on recorded evidence.

Free conversation remains a separate session type and does not pretend to complete curricular objectives.

### Active correction

A correction is not mastered when displayed. The learner must retry the corrected phrase or answer a transfer prompt. The attempt is stored as evidence and may schedule a review item.

### Review item

`ReviewItem` represents vocabulary, a correction pattern, a listening item, or a pronunciation target. Scheduling uses a deterministic local algorithm with four grades: Again, Hard, Good, Easy.

### Audio evidence

The product may retain an audio attempt only when the learner enables recording history. Each retained item has a purpose, duration, creation time, and delete control. The first pronunciation release provides replay, reference audio, and intelligibility evidence; phoneme-level scoring is gated behind a validated benchmark.

## Service boundaries

- `learning/profile.py`: learner preferences and onboarding state.
- `learning/diagnostic.py`: baseline assessment and CEFR evidence.
- `learning/curriculum.py`: objectives and prerequisite progression.
- `learning/planner.py`: selects the next guided session.
- `learning/review.py`: spaced-repetition scheduling.
- `learning/mastery.py`: aggregates independent evidence without using activity as mastery.
- `learning/listening.py`: deterministic listening exercise state and grading.
- `learning/pronunciation.py`: audio comparison boundary and validation state.
- `storage/learning_repository.py`: persistence interface over SQLite.
- `ui/`: presentation only; no scheduling or mastery rules.

## Progress evidence

The progress screen separates:

- activity: sessions, active minutes, turns;
- performance: independent task success by skill;
- retention: delayed review success;
- reliability: transcript edits and recognition uncertainty.

Active practice time is measured by explicit activity intervals, not the wall-clock distance between the first and last message.

## Product releases

### Release 1 — Direction

Onboarding, learner goals, diagnostic baseline, skill taxonomy, honest active-time tracking, and a “Today” recommendation.

### Release 2 — Teaching loop

Guided sessions, measurable scenario objectives, active correction retries, correction preferences, and independent challenge evidence.

### Release 3 — Memory

Real vocabulary items, spaced repetition, recurring-error patterns, delayed review, and mastery views.

### Release 4 — Speech and listening

Optional audio history, self-replay, reference comparison, listening exercises, speech-rate control, and multiple validated voices/accents.

### Release 5 — Daily product

Daily target, resume flow, reminders where the operating system permits them, first-run diagnostics, backup/import/export, and release acceptance testing.

## Success criteria

- A new learner can complete onboarding and receive a justified first activity without editing files.
- Every guided session has exactly one primary objective and one independent challenge.
- Corrections marked learned have at least one successful retry and one delayed review.
- Progress never labels activity volume as proficiency.
- Audio history is opt-in and deletable from the UI.
- A clean installation can diagnose missing microphone, Ollama, and cached models with actionable messages.
- Backup export followed by import recreates profile, curriculum state, reviews, and history on a fresh database.

## Coverage of the 20 product gaps

| Gap | Design response |
|---|---|
| Initial level | Diagnostic baseline |
| CEFR progression | Per-skill CEFR evidence and objectives |
| Learning plan | Planner and Today recommendation |
| Lesson structure | Guided session stages |
| Passive corrections | Retry and transfer prompt |
| No spaced repetition | Review scheduler |
| Weak vocabulary tracker | Vocabulary learning items |
| No pronunciation work | Audio evidence and validated assessor boundary |
| Recognition contamination | Recognition reliability kept separate from language evidence |
| No self-listening | Optional audio history and replay |
| Weak listening practice | Gist/detail exercises |
| Limited auditory exposure | Rate, voice, and accent variants |
| Unmeasurable scenarios | Objective-backed scenario templates |
| No recurring-error adaptation | Error-pattern aggregation and planner input |
| Activity-only metrics | Performance and retention views |
| Inaccurate practice time | Explicit active intervals |
| No retention measurement | Delayed review outcomes |
| Fixed correction style | Learner correction preferences |
| Weak habit loop | Daily target and resume flow |
| Fragile onboarding/data | Diagnostics and portable backup |
