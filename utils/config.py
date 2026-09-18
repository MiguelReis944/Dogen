"""Dogen's local configuration file."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from nlp.llm import SYSTEM_PROMPT


@dataclass
class AppConfig:
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "mistral"
    whisper_model: str = "base"
    tts_model: str = "tts_models/en/ljspeech/tacotron2-DDC"
    mic_device: int | None = None
    speaker_device: int | None = None
    vad_threshold: float = 0.02
    silence_duration_sec: float = 2.0
    context_size: int = 10
    system_prompt: str = SYSTEM_PROMPT


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    if not path.exists():
        return AppConfig()
    return AppConfig(**json.loads(path.read_text(encoding="utf-8")))


def save_config(config: AppConfig, path: str | Path) -> None:
    Path(path).write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
