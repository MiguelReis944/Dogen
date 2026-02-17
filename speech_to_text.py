import speech_recognition as sr
from terminal_style import Cores

async def listen():
    estilo = Cores

    r = sr.Recognizer()

    with sr.Microphone() as source:
        print("Ouvindo...")
        audio = r.listen(
            source,
            timeout=None,
            phrase_time_limit=None
        )


    try:
        text = r.recognize_google(audio, language="pt-BR,en-US").lower()

        print(estilo.usuario(text))
        return text.lower()
    except:
        return ""

