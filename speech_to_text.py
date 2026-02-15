import speech_recognition as sr

def listen():

    r = sr.Recognizer()

    with sr.Microphone() as source:
        print("Ouvindo...")
        audio = r.listen(
            source,
            timeout=None,
            phrase_time_limit=None
        )


    try:
        text = r.recognize_google(audio, language="pt-BR,en-US")
        print("Você disse:", text)
        return text.lower()
    except:
        return ""

