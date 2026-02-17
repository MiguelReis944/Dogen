import asyncio
from speech_to_text import listen
from ai_response import ask_ai
from command_handler import handle_command
from text_to_speech import speak
from terminal_style import Cores
from memory_manager import carregar_memoria
from memory_manager import adicionar_memoria

async def main():
    
    while True:
        chat_history = carregar_memoria()
        estilo = Cores

        text = await listen()

        if text == "":
            continue
        adicionar_memoria("user", text, chat_history)

        action = await handle_command(text)
        
            # Comandos para sair
        if text in ["sair", "tchau", "encerrar", "parar","até mais"]:
            print(estilo.assistente("Até mais! Fechando programa."))
            adicionar_memoria("user", text, chat_history)
            await speak("Até mais! Fechando programa.")
            adicionar_memoria("assistant", "Até mais! Fechando programa.", chat_history)
            break

        if action:
            adicionar_memoria("tool", action, chat_history)
            print(estilo.assistente(action))
            await speak(action)
        else:
            reply = await ask_ai(text,chat_history)
            adicionar_memoria("assistant", reply, chat_history)
            print(estilo.assistente(reply))
            await speak(reply)

if __name__ == "__main__":
    asyncio.run(main())