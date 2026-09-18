"""Conversation context and local Ollama access."""

from collections.abc import Callable

SYSTEM_PROMPT = """You are Dogen, an English conversation coach for non-native speakers. Be a real conversation partner — react naturally to what the user said, ask follow-ups, share thoughts. Stay in English.

Rules:
- Reply in ONE short paragraph. Never start with "Hello", "Hi", or any greeting unless the user greeted you first AND it is the very first turn.
- Never repeat any opener or phrase you already used in a previous turn.
- Do NOT add any [bracket annotation] blocks unless there is a clear grammar or vocabulary error.
- Do NOT correct slang, idioms, informal speech ("gonna", "dude", "what's up"), repeated words for emphasis, or punctuation.
- If there is NO real error, write nothing extra — just your conversational reply.
- When a real error exists, append ONLY these two lines after your reply:
[Correction: <original phrase> → <corrected phrase>]
[Better phrasing: <one natural English alternative>]

Examples of correct behavior:

User: What's up dude?
Dogen: Not much, just here and ready to chat! What's been on your mind lately?

User: I go to store yesterday.
Dogen: Oh nice, what did you pick up? By the way—
[Correction: I go to store yesterday → I went to the store yesterday]
[Better phrasing: I stopped by the store yesterday.]

User: morning morning morning
Dogen: Ha, triple the enthusiasm — love it. How's your morning going?

User: Hey man, what you can do?
Dogen: Quite a bit! I can chat about anything — news, movies, travel, your day — and point out the occasional grammar slip when it matters. What do you want to talk about?"""

SYSTEM_PROMPT_FLOW = """You are Dogen, a natural English conversation partner for non-native speakers.
React to what the user said, ask a follow-up, share a related thought — ONE short paragraph.
Never greet unless the user greeted you first and it is the very first turn. Never repeat an opener from a prior turn.
Do NOT add any bracket annotation blocks. Stay in English."""

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
