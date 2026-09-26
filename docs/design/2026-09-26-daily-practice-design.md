# Dogen Daily Practice — Design

**Date:** 2026-09-26

**Status:** Approved for planning

**Product direction:** An offline, private English conversation coach that is reliable enough for daily practice.

## Problem

Dogen already has the right core loop—record, transcribe, answer, speak, and save the session—but three failures keep that loop from becoming a habit:

1. automatic recording may stop before the learner has finished speaking;
2. transcription may misunderstand the intended sentence;
3. spoken responses are not yet comfortable enough to listen to repeatedly.

The current summary also reports activity, corrections, and filler words, but it does not show whether the learner is improving across days. The product therefore feels like a technical demonstration rather than a dependable learning tool.

## Goal

Make Dogen useful for a real 15–30 minute daily English conversation session while keeping its differentiator: all speech, conversation history, and progress data remain local.

The release is successful when a learner can:

- choose push-to-talk for guaranteed control or automatic mode for convenience;
- finish normal sentences without being cut off;
- inspect and repair an uncertain transcript before it reaches the tutor;
- hear, stop, and replay a natural response;
- receive corrections without the correction text polluting the spoken answer;
- review honest weekly progress based on observable behavior;
- understand where each stage of the application lives in the architecture.

## Non-goals

This release does not attempt to reproduce TalkPal's entire product surface. It will not add a language curriculum, proficiency levels, mobile clients, cloud synchronization, fictional characters, image conversations, dozens of languages, or a pronunciation score presented as scientifically precise.

Pronunciation scoring is specifically deferred. A trustworthy implementation needs phoneme alignment, reference pronunciations, confidence calibration, and validation across accents. Dogen may later show pronunciation evidence, but it must not invent a score from a language model's opinion.

## Product scope

### 1. Reliable turn capture

Push-to-talk is the dependable default for a first daily-use release. Automatic VAD remains available and gains visible pause presets. Every capture records why it ended: silence, button release, timeout, or cancellation. This makes premature endings diagnosable instead of mysterious.

The VAD's measured noise floor is retained between turns. At present the recorder creates an adaptive detector for a turn but does not carry the detector's final noise estimate back into the next turn. Fixing that feedback loop makes automatic mode better suited to a stable room without adding a second audio system.

### 2. Reproducible transcription tuning

Transcription quality will be measured on a small local evaluation set recorded with the user's actual microphone and accent. The clips remain untracked and private. A manifest contains the expected text, and a script compares Whisper configurations and noise reduction using word error rate and manual-edit rate.

Noise reduction becomes configurable because denoising can help a noisy recording while damaging a clean one. The project chooses a default from measurements on the target machine, not from intuition.

### 3. Comfortable response audio

The existing streaming sentence pipeline stays: it minimizes perceived latency and already separates coaching tags from spoken text. The UI gains explicit stop and replay actions. Replay reuses the last clean assistant response through the same synthesizer rather than storing permanent audio.

The initial voice decision is evidence-driven. LJSpeech and the already-supported local alternatives are compared for intelligibility, startup cost, time-to-first-audio, and subjective naturalness. A playback-speed control is not included until the selected model has a pitch-preserving implementation; fast, distorted audio would not improve practice.

### 4. Structured coaching feedback

The conversational reply and coaching feedback become separate domain values. The model may still emit compact tags, but one parser owns their interpretation. The UI renders the reply as dialogue and the correction as feedback. Text-to-speech receives only the reply.

Feedback categories are deliberately small and comprehensible:

- grammar;
- vocabulary;
- word order;
- verb tense;
- agreement;
- preposition;
- natural phrasing.

The categories describe observed corrections. They are not diagnoses of language proficiency.

### 5. Honest local progress

Each completed learner turn stores objective metrics: word count, filler-word count, whether the transcript was edited, whether a correction was produced, and the correction category. A progress view derives:

- days practiced and current streak;
- total practice time and completed turns;
- words spoken;
- filler words per 100 words;
- transcript edit rate;
- corrections by category;
- vocabulary encountered.

The progress view compares recent periods only when enough data exists. It says “not enough data” instead of implying improvement from one session.

## Architecture

The existing layered pipeline remains intact:

```text
MainWindow
   ↓ user controls / rendered state
ConversationWorker
   ↓
Recorder → Transcriber → ProcessingPipeline → LocalLLM
   ↓               ↓                  ↓
capture result   transcript review     TurnResult
                                           ├─ reply text → Synthesizer → AudioPlayer
                                           └─ CoachFeedback → UI + SQLite

SQLite → ProgressStats → ProgressDialog
```

The important boundaries are:

- `Recorder` owns audio capture and reports a typed capture result.
- `Transcriber` owns speech-to-text, not transcript editing UI.
- `ProcessingPipeline` coordinates one turn and returns a typed turn result.
- `feedback.py` is the only place that parses coaching markup.
- `Database` stores facts; `ProgressStats` computes presentation-ready aggregates.
- `MainWindow` owns interaction state but does not implement audio or statistics algorithms.

No event bus, dependency injection container, background service, or plugin system is introduced. The application is small enough for explicit constructor dependencies and PyQt signals.

## Data changes

SQLite migrations remain additive through `CREATE TABLE IF NOT EXISTS`.

`turn_metrics` stores one row per completed user turn:

```text
session_id, created_at, word_count, filler_count,
transcript_edited, correction_category
```

The existing `conversations` and `vocab` tables remain the source for dialogue history and encountered vocabulary. Old sessions remain readable; their missing metrics are simply excluded from rate comparisons.

## Failure behavior

- Empty or low-confidence audio returns to listening without adding a turn.
- A cancelled or retried transcript is not committed to LLM context or SQLite.
- Barge-in stops response playback and begins a new capture without saving a partial assistant reply.
- Replay cannot alter conversation context or statistics.
- If TTS fails, the written response remains visible and the next turn can continue.
- If Ollama is unavailable, the UI shows an actionable local-service error and preserves the session.

## Acceptance criteria

The release candidate must meet all of these on the user's machine:

1. Push-to-talk completes 20 of 20 test utterances without a premature cut.
2. The selected automatic pause preset produces no more than 2 premature cuts in 20 natural utterances.
3. The selected transcription configuration reduces manual transcript edits by at least 30% relative to the recorded baseline, or the report clearly retains the old default when no configuration achieves that result.
4. A spoken response can be stopped and replayed without creating an extra conversation turn.
5. Coaching text is never sent to TTS.
6. A correction appears separately and is persisted with one supported category.
7. Weekly progress is derived from stored turns and handles empty, legacy, and single-day data without misleading comparisons.
8. Ten consecutive manual conversations complete without a crash or unrecoverable state.
9. Automated tests pass, and the README explains the pipeline, privacy boundary, operating modes, and metric limitations.

## Delivery order

Work proceeds in vertical checkpoints:

1. capture observability and VAD correctness;
2. turn controls and transcript benchmark;
3. response playback quality;
4. structured feedback;
5. persistent progress;
6. seven-day dogfooding and release hardening.

Each checkpoint must be usable and committed independently. If time becomes scarce, Dogen can ship after checkpoint 3 as a reliable conversation tool; feedback and progress improve learning value but must not delay basic audio reliability.
