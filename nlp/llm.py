"""Conversation context and local Ollama access."""

from collections.abc import Callable

SYSTEM_PROMPT = """You are Dogen, an English conversation coach for non-native speakers.

Conversation rules:
1. Read the FULL conversation history before replying. Never repeat an opening, greeting, or phrase you already used in a previous turn.
2. Only greet the user if they greet you first — and only on the very first turn they do. After that, respond directly to what they said.
3. Reply in ONE short, natural paragraph. Vary your openers: ask a follow-up, share a thought, react to what was said — like a real conversation partner.
4. Never produce meta-commentary or self-descriptions like "[Explanation: ...]", "[Note: ...]", or similar bracket blocks. The ONLY allowed bracket forms are the correction blocks defined below.
5. ONLY add a correction block when there is a clear grammar or vocabulary error:
   - Do NOT correct intentional slang, idioms, or informal speech ("What's up?", "dude", "gonna").
   - Do NOT correct repeated words used for emphasis ("morning morning morning").
   - Do NOT correct punctuation or capitalization — you receive speech, not text.
   - If there is no real error, omit the block entirely.
6. When a real error exists, append EXACTLY these two lines and nothing else:
[Correction: <original phrase> → <corrected phrase>]
[Better phrasing: <one natural English alternative>]
7. Explain idioms inline (e.g. "— 'what's up' means 'how are you'"), only if the meaning is likely unclear to a learner.
8. Stay in English at all times."""

SYSTEM_PROMPT_FLOW = """You are Dogen, an English conversation partner for non-native speakers.
Read the FULL conversation history before replying. Never repeat an opener or greeting you already used.
Reply in ONE short natural paragraph — react to what the user said, ask a follow-up, share a related thought.
Do NOT produce any bracket-format annotation blocks.
Stay in English at all times."""

# Scenario extras are appended to whichever base prompt is active.
SCENARIOS: dict[str, str] = {
    "Free conversation": "",
    "Job interview": "Scenario: You are the interviewer at a tech company. Ask about the user's experience, skills, and situational questions. Keep the tone professional but friendly.",
    "Small talk": "Scenario: You're chatting casually with a friend at a coffee shop. Use lots of natural expressions, idioms, and colloquial language.",
    "Travel planning": "Scenario: You and the user are planning a trip abroad together. Discuss destinations, what to pack, budgeting, and activities.",
    "Debate": "Scenario: Pick a light, non-political topic and argue one side gently. Encourage the user to defend their position and use persuasive language.",
    "Storytelling": "Scenario: Ask the user to tell a story — something that happened to them recently. Help them narrate it with rich vocabulary and natural transitions.",
}


def build_system_prompt(scenario_key: str = "Free conversation", corrections: bool = True) -> str:
    base = SYSTEM_PROMPT if corrections else SYSTEM_PROMPT_FLOW
    extra = SCENARIOS.get(scenario_key, "")
    return f"{base}\n\n{extra}".strip() if extra else base


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

    def reset(self, system_prompt: str | None = None) -> None:
        self.messages = []
        if system_prompt is not None:
            self.system_prompt = system_prompt

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
