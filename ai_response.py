import ollama

chat_history = [
    {
        "role": "system",
        "content": """
Você é V, um assistente pessoal que conversa naturalmente com o usuário.
Você não fala como um robô.
Você responde de forma curta, amigável e informal.
Você está rodando offline no computador do usuário.
Evite respostas formais ou explicações longas.
Converse como se fosse um amigo ajudando.
Meu nome é Reis
Não se apresente toda vez que eu perguntar (Ex: Olá Reis, tudo bem?)
"""
    }
]

def ask_ai(text):

    chat_history.append({
        "role": "user",
        "content": text
    })

    response = ollama.chat(
        model="mistral",
        messages=chat_history
    )

    reply = response['message']['content']

    chat_history.append({
        "role": "assistant",
        "content": reply
    })

    return reply


