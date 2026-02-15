import pyttsx3
import threading
import state

def speak(text):

    def run():

        state.speaking = True
        state.stop_speaking = False

        engine = pyttsx3.init()

        voices = engine.getProperty('voices')
        engine.setProperty('voice', voices[1].id)

        engine.setProperty('rate', 170)

        engine.say(text)

        while engine._inLoop:
            if state.stop_speaking:
                engine.stop()
                break

        engine.runAndWait()

        state.speaking = False

    threading.Thread(target=run).start()
