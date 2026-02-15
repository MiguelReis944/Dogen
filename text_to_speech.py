import pyttsx3

def speak(text):

    engine = pyttsx3.init()

    voices = engine.getProperty('voices')
    engine.setProperty('voice', voices[0].id)

    engine.setProperty('rate', 250)
    engine.setProperty('volume', 1)

    engine.say(text)
    engine.runAndWait()
    engine.stop()
