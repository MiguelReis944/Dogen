import asyncio
from speech_to_text import listen
from ai_response import ask_ai
from command_handler import handle_command
from text_to_speech import speak
from terminal_style import Cores

numero_comandos = 0

async def main():
    global numero_comandos
    
    while True:
        estilo = Cores

        text = await listen()

        if text == "":
            continue

        action = await handle_command(text)
        
            # Comandos para sair
        if text in ["sair", "tchau", "encerrar", "parar", "exit", "quit", "até mais"]:
            print(estilo.assistente("Até mais!"))
            await speak("Até mais!")
            break

        if action:
            print(estilo.assistente(action))
            await speak(action)
            numero_comandos = numero_comandos + 1
        else:
            reply = await ask_ai(text)
            print(estilo.assistente(reply))
            await speak(reply)
            numero_comandos = numero_comandos + 1

if __name__ == "__main__":
    asyncio.run(main())