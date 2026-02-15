import pyttsx3
import threading
from queue import Queue

engine = pyttsx3.init()
tts_queue = Queue()

def tts_worker():
    while True:
        text = tts_queue.get()

        if text is None:
            break

        engine.say(text)
        engine.runAndWait()

def start_tts():
    threading.Thread(target=tts_worker, daemon=True).start()

def speak(text):
    engine.stop()          # interrompe fala atual
    tts_queue.queue.clear() # limpa fila antiga
    tts_queue.put(text)
