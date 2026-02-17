import json
import os
from datetime import datetime

HISTORY_FILE = "history.json"

def carregar_memoria():
    if not os.path.exists(HISTORY_FILE) or os.path.getsize(HISTORY_FILE) == 0:
        history = [{
            "role": "system",
            "content": """Você é Dogen(Desktop Oriented General Execution Navigator), um assistente pessoal amigável e descontraído.

Características:
- Fala como um amigo, não como um robô
- Respostas curtas e diretas (máximo 2-3 frases)
- Usa linguagem casual e brasileira
- Faz perguntas para manter a conversa
- Tem senso de humor leve
- É prestativo sem ser formal

Regras:
- Não se apresentar repetidamente
- Não usar linguagem técnica excessiva
- Evitar respostas genéricas
- Ser natural como uma conversa de WhatsApp
- Responder sempre em português do Brasil
- Se não souber algo, admite naturalmente
- Não usar emojis
"""
        }]

        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        return history

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)

            if len(history) == 0:
                return carregar_memoria()

            return history

    except json.JSONDecodeError:
        os.remove(HISTORY_FILE)
        return carregar_memoria()

def salvar_memoria(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def adicionar_memoria(role, content, history):

    if not content:
        return

    hora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    history.append({
        "data/hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "role": role,
        "content": content
    })

    salvar_memoria(history)

def filtrar_memoria_para_ia(history):

    mensagens = []

    for msg in history:

        if msg["role"] == "tool":
            mensagens.append({
                "role": "assistant",
                "content": f"O sistema executou a seguinte ação anteriormente: {msg['content']}"
            })

        else:
            mensagens.append({
                "role": msg["role"],
                "content": msg["content"]
            })

    return mensagens