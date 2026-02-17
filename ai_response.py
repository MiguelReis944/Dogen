import ollama
from memory_manager import filtrar_memoria_para_ia

async def ask_ai(text, chat_history):

    mensagens = filtrar_memoria_para_ia(chat_history)

    response = ollama.chat(
        model="mistral",
        messages=mensagens
    )

    reply = response['message']['content']

    return reply



