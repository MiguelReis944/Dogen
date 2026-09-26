"""Dogen's local configuration file."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from nlp.llm import SYSTEM_PROMPT


@dataclass
class AppConfig:
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "mistral"
    whisper_model: str = "base"
    tts_model: str = "tts_models/en/ljspeech/tacotron2-DDC"
    tts_speaker: str | None = None  # required for multi-speaker models (e.g. VCTK)
    mic_device: int | None = None
    speaker_device: int | None = None
    vad_threshold: float = 0.02
    silence_duration_sec: float = 2.0
    context_size: int = 10
    input_mode: str = "ptt"  # "vad" | "ptt"
    review_transcript: bool = False  # show editable transcript before sending to LLM
    noise_reduction: bool = True
    system_prompt: str = SYSTEM_PROMPT

    def __post_init__(self):
        url = urlparse(self.ollama_host)
        if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Ollama host must be an http://localhost address for offline use")


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    if not path.exists():
        return AppConfig()
    known = {f.name for f in AppConfig.__dataclass_fields__.values()}
    data = {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if k in known}
    return AppConfig(**data)


def save_config(config: AppConfig, path: str | Path) -> None:
    Path(path).write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
