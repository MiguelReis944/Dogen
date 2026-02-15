import os
import subprocess

def handle_command(text):

    if "crie uma pasta" in text:
        name = text.replace("crie uma pasta chamada", "")
        os.makedirs(name.strip(), exist_ok=True)
        return "Pasta criada"

    if "abra o vs code" in text:
        subprocess.Popen("code")
        return "Abrindo VS Code"

    return None
