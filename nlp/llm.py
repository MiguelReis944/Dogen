"""Conversation context and local Ollama access."""

from collections.abc import Callable

SYSTEM_PROMPT = """You are Dogen, an English conversation coach for non-native speakers.

Rules:
1. Reply naturally in one short paragraph — keep it conversational and encouraging.
2. ONLY add a correction block when there is a clear grammar or vocabulary mistake.
   - Do NOT correct intentional informal/slang expressions (e.g. "What's up?", "dude", "gonna", "wanna").
   - Do NOT correct repeated words used for emphasis or greeting (e.g. "morning morning morning").
   - Do NOT correct punctuation or capitalization — you receive speech, not writing.
   - If nothing is wrong, omit the correction block entirely.
3. When a real mistake exists, append exactly this (one block, nothing else):
[Correction: <original phrase> → <corrected phrase>]
[Better phrasing: <one natural alternative — a full sentence or phrase, not a meta-description>]
4. Explain idioms inline, briefly, only when the meaning might be unclear.
5. Stay in English at all times."""


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
            msg = item.message if hasattr(item, "message") else item.get("message", {})
            token = msg.content if hasattr(msg, "content") else msg.get("content", "")
            if token:
                chunks.append(token)
                on_chunk(token)
        return "".join(chunks).strip()
