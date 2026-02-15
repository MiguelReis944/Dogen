import ollama

def ask_ai(prompt):

    response = ollama.chat(
        model='mistral:latest',
        messages=[
            {
                'role': 'system',
                'content': '''
You are V, an offline personal assistant.

My name is Reis.
Rules:
- Be direct
- Don't be verbose
- Prioritize completing tasks
- Explain things simply
- Speak informally and casually
- Always try to teach me
'''
            },
            {
                'role': 'user',
                'content': prompt
            }
        ]
    )

    return response['message']['content']

