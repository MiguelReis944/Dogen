"""Evaluate local Whisper transcription against a private audio manifest."""

import argparse
import json
import math
import re
import statistics
import time
from pathlib import Path


_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def normalize_text(text: str) -> list[str]:
    return _WORD_RE.findall(text.casefold())


def word_error_rate(expected: str, actual: str) -> float:
    reference = normalize_text(expected)
    hypothesis = normalize_text(actual)
    if not reference:
        return 0.0 if not hypothesis else 1.0

    previous = list(range(len(hypothesis) + 1))
    for row, expected_word in enumerate(reference, start=1):
        current = [row]
        for column, actual_word in enumerate(hypothesis, start=1):
            substitution = previous[column - 1] + (expected_word != actual_word)
            insertion = current[column - 1] + 1
            deletion = previous[column] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1] / len(reference)


def summarize(results: list[dict]) -> dict:
    if not results:
        return {
            "clips": 0,
            "median_wer": None,
            "mean_wer": None,
            "median_runtime_sec": None,
        }
    return {
        "clips": len(results),
        "median_wer": statistics.median(item["wer"] for item in results),
        "mean_wer": statistics.fmean(item["wer"] for item in results),
        "median_runtime_sec": statistics.median(item["runtime_sec"] for item in results),
    }


def _load_audio(path: Path):
    import numpy as np
    from scipy.io import wavfile
    from scipy.signal import resample_poly

    sample_rate, samples = wavfile.read(path)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if np.issubdtype(samples.dtype, np.integer):
        scale = float(max(abs(np.iinfo(samples.dtype).min), np.iinfo(samples.dtype).max))
        samples = samples.astype(np.float32) / scale
    else:
        samples = samples.astype(np.float32)
    if sample_rate != 16000:
        divisor = math.gcd(sample_rate, 16000)
        samples = resample_poly(samples, 16000 // divisor, sample_rate // divisor).astype(np.float32)
    return samples


def _read_manifest(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("manifest must be a non-empty JSON list")
    for index, item in enumerate(data):
        if not isinstance(item, dict) or not isinstance(item.get("audio"), str):
            raise ValueError(f"manifest item {index} needs an audio path")
        if not isinstance(item.get("expected"), str):
            raise ValueError(f"manifest item {index} needs expected text")
    return data


def evaluate(manifest_path: Path, model_name: str, noise_reduction: bool) -> dict:
    from audio.recorder import _denoise
    from nlp.transcriber import Transcriber

    manifest = _read_manifest(manifest_path)
    loaded_at = time.perf_counter()
    transcriber = Transcriber(model_name)
    model_load_sec = time.perf_counter() - loaded_at
    results = []
    for item in manifest:
        audio_path = (manifest_path.parent / item["audio"]).resolve()
        if not audio_path.is_file():
            raise FileNotFoundError(f"audio clip not found: {audio_path}")
        samples = _load_audio(audio_path)
        if noise_reduction:
            samples = _denoise(samples, 16000)
        started = time.perf_counter()
        transcript = transcriber.transcribe(samples).strip()
        runtime_sec = time.perf_counter() - started
        results.append({
            "audio": item["audio"],
            "expected": item["expected"],
            "transcript": transcript,
            "wer": word_error_rate(item["expected"], transcript),
            "runtime_sec": runtime_sec,
        })
    return {
        "model": model_name,
        "noise_reduction": noise_reduction,
        "model_load_sec": model_load_sec,
        "summary": summarize(results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--noise-reduction",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="apply the same post-capture noise reduction used by Dogen",
    )
    args = parser.parse_args()
    try:
        report = evaluate(args.manifest, args.model, args.noise_reduction)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
