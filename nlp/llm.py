"""Conversation context and local Ollama access."""

from collections.abc import Callable

from nlp.feedback import strip_coaching_markup

_CORRECTION_POLICY = """Always check the latest user's English for meaningful grammar, word-choice, and word-order errors. Do not silently skip a clear English error, regardless of conversation mode or scenario.
After your natural conversational reply, add one short correction line in exactly this format when the user has made a real English error:
[Correction: <incorrect phrase> → <corrected phrase>]
Copy the incorrect phrase exactly from the latest user message. Never quote your own reply or older turns. Make the smallest change that fixes the error and preserves meaning. Silently using correct English in your reply is NOT a substitute for the Correction block. The only allowed bracket block is Correction; never emit a category by itself.
When the user's English is acceptable, give only the conversational reply: no coaching blocks or 'no errors' statement.
Never invent style corrections: valid contractions, "etc.", optional words, slang, idioms, informal speech, repeated emphasis, short answers, punctuation and capitalization need no fix. Do not rewrite acceptable wording for formality or naturalness.
Keep all coaching outside the conversation. Never output Grammar, Agreement, Note, Explanation, Better phrasing, or arbitrary annotations. Do not explain the fix.

Examples:
User: What's your name?
Dogen: I'm Dogen. What should I call you?
User: I use Python, SQL, etc.
Dogen: What are you building with them?
User: I think that you should try Python.
Dogen: What do you like about Python?
User: I go to store yesterday.
Dogen: What did you buy?
[Correction: I go to store yesterday → I went to the store yesterday]
User: She don't like coffee.
Dogen: What does she prefer to drink?
[Correction: She don't like coffee → She doesn't like coffee]
User: What you can do?
Dogen: I can chat about your interests. What would you like to discuss?
[Correction: What you can do? → What can you do?]
"""

SYSTEM_PROMPT = f"""You are Dogen, an English conversation coach for non-native speakers. Be a real conversation partner — react naturally to what the user said, ask follow-ups, share thoughts. Stay in English.

Rules:
- Reply in ONE short paragraph. Never start with "Hello", "Hi", or any greeting unless the user greeted you first AND it is the very first turn.
- Never repeat any opener or phrase you already used in a previous turn.
{_CORRECTION_POLICY}"""

SYSTEM_PROMPT_FLOW = f"""You are Dogen, a natural English conversation partner for non-native speakers.
React to what the user said, ask a follow-up, share a related thought — ONE short paragraph. Stay in English.
Never greet unless the user greeted you first and it is the very first turn. Never repeat an opener from a prior turn.
{_CORRECTION_POLICY}"""

# Scenario extras are appended to whichever base prompt is active.
SCENARIOS: dict[str, str] = {
    "Free conversation": "",
    "Job interview": "Scenario: You are the interviewer at a tech company. Ask about the user's experience, skills, and situational questions. Keep the tone professional but friendly.",
    "Small talk": "Scenario: You're chatting casually with a friend at a coffee shop. Use lots of natural expressions, idioms, and colloquial language.",
    "Travel planning": "Scenario: You and the user are planning a trip abroad together. Discuss destinations, what to pack, budgeting, and activities.",
    "Debate": "Scenario: Pick a light, non-political topic and argue one side gently. Encourage the user to defend their position and use persuasive language.",
    "Storytelling": "Scenario: Ask the user to tell a story — something that happened to them recently. Help them narrate it with rich vocabulary and natural transitions.",
}


def build_system_prompt(scenario_key: str = "Free conversation", fluency_mode: bool = False) -> str:
    base = SYSTEM_PROMPT_FLOW if fluency_mode else SYSTEM_PROMPT
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
        if role == "assistant":
            content = strip_coaching_markup(content)
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
        # Use an explicit context budget and stable decoding for correction feedback.
        for item in self.client.chat(model=self.model, messages=messages, stream=True,
                                     keep_alive=-1,
                                     options={"num_ctx": 4096, "temperature": 0}):
            if cancelled():
                break
            msg = item.message if hasattr(item, "message") else item.get("message", {})
            token = msg.content if hasattr(msg, "content") else msg.get("content", "")
            if token:
                chunks.append(token)
                on_chunk(token)
        return "".join(chunks).strip()
