"""Conversation context and local Ollama access."""

from collections.abc import Callable

SYSTEM_PROMPT = """You are Dogen, an English conversation coach for non-native speakers.
Gently correct grammar and suggest better phrasing. Explain idioms when useful.
If pronunciation cannot be inferred from the transcript, do not pretend you heard it.
Keep responses concise (one or two short paragraphs), encouraging, and in English.
Remember the context of the conversation."""


class ConversationContext:
    def __init__(self, max_history: int = 10, system_prompt: str = SYSTEM_PROMPT):
        self.max_history = max_history
        self.system_prompt = system_prompt
        self.messages: list[dict[str, str]] = []

    def add_message(self, role: str, content: str) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("Unsupported conversation role")
        self.messages.append({"role": role, "content": content})
        self.messages = self.messages[-2 * self.max_history:]

    def get_messages_for_ollama(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.system_prompt}, *self.messages]


class OllamaClient:
    def __init__(self, host: str, model: str, timeout: float = 60):
        import ollama
        self.client = ollama.Client(host=host, timeout=timeout)
        self.model = model

    def generate(self, messages: list[dict[str, str]], on_chunk: Callable[[str], None], cancelled: Callable[[], bool]) -> str:
        chunks = []
        for item in self.client.chat(model=self.model, messages=messages, stream=True):
            if cancelled():
                break
            token = item["message"]["content"]
            chunks.append(token)
            on_chunk(token)
        return "".join(chunks).strip()
