# Daily Practice Baseline

## Purpose

This baseline measures whether Dogen becomes more reliable for daily spoken-English practice. Private voice recordings, manifests, and generated evaluation files belong in `local-evaluation/` and must never be committed.

## Initial field sample

Source: `2026-09-26 15-46-44.mp4` (private, not copied into the repository).

| Metric | Observation |
|---|---:|
| Capture duration | 96.6 seconds |
| Video resolution / frame rate | 1920×1080 / 60 fps |
| Learner submissions observed | 2 |
| Completed assistant responses observed | 2 |
| Premature cuts reported | 0 |
| Failed or stuck turns observed | 0 |
| Known transcript edits needed | 1 |

The known error was `upgrade` transcribed as `pigrade`. A second offline transcription of the whole video with `small.en` also misunderstood that portion, which points to speech recognition or captured pronunciation rather than an LLM response defect.

This sample confirms that the end-to-end loop can complete, but two learner turns are not enough to calculate a trustworthy error rate or choose another Whisper model. It is retained as qualitative baseline evidence only.

## Repeatable protocol

Record the same utterance set without changing settings during a run.

### Utterance set

1. Ten short utterances containing 3–7 words.
2. Ten natural utterances containing a pause of 1–2 seconds.
3. Ten utterances containing names, technical terms, or numbers.

Run all 30 utterances in each combination:

- push-to-talk in a quiet room;
- automatic mode in a quiet room;
- push-to-talk with normal background noise;
- automatic mode with normal background noise.

### Per-utterance fields

Record these fields in the private manifest:

```json
{
  "audio": "001.wav",
  "expected": "I want to upgrade this application",
  "mode": "ptt",
  "environment": "quiet",
  "captured_duration_sec": 3.4,
  "stop_reason": "ptt_release",
  "transcript": "I want to upgrade this application",
  "manual_edit_needed": false,
  "time_to_first_audio_sec": 7.2,
  "failed_or_stuck": false
}
```

### Aggregate report

For each mode and environment, report:

```text
premature cuts / attempts
manual transcript edits / attempts
median time to first audible response
failed or stuck turns / attempts
```

## Formal baseline status

The full 120-attempt protocol requires the learner's microphone, room conditions, and spoken English. It remains pending and must be completed before selecting a new Whisper model or claiming a measured accuracy improvement. Implementation may add observability and evaluation tooling without presenting the initial field sample as a statistically valid benchmark.
