import speech_recognition as sr

def listen():

    r = sr.Recognizer()

    with sr.Microphone() as source:
        print("Ouvindo...")
        audio = r.listen(source)

    try:
        text = r.recognize_google(audio, language="pt-BR,en-US")
        print("Você disse:", text)
        return text.lower()
    except:
        return ""
