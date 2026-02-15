from speech_to_text import listen
from ai_response import ask_ai
from command_handler import handle_command
from text_to_speech import speak

numero_comandos = 0

while True:

    text = listen()

    if text == "":
        continue

    action = handle_command(text)

    if action:
        print("V:", action)
        speak(action)
        numero_comandos = numero_comandos + 1
    else:
        reply = ask_ai(text)
        print("V:", reply)
        speak(reply)
        numero_comandos = numero_comandos + 1