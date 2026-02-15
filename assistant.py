from tts_manager import speak, start_tts
from speech_to_text import listen
from ai_response import ask_ai
from command_handler import handle_command
from text_to_speech import speak

start_tts()

while True:

    text = listen()

    if text == "":
        continue

    action = handle_command(text)

    if action:
        print("V:", action)
        speak(action)
    else:
        reply = ask_ai(text)
        print("V:", reply)
        speak(reply)
