import os
import subprocess
import webbrowser


async def handle_command(text):

    #comandos no explorador de arquivos

    if "criar pasta" in text:
        # Remove a parte "crie uma pasta" do texto
        name = text.lower()

        name = name.replace("criar pasta", "")
        name = name.replace("crie uma pasta", "")
        name = name.replace("crie pasta", "")
        name = name.replace("criar uma pasta", "")
        name = name.replace("chamada", "")
        name = name.replace("com o nome", "")
        name = name.replace("de nome", "")

        name = name.strip()

    
        # Se não sobrou nada, usa nome padrão
        if not name:
            name = "Nova Pasta"
    
        os.makedirs(name, exist_ok=True)
        return f"Pasta '{name}' criada"

    if "listar arquivos" in text:
        arquivos = os.listdir()
        return f"Arquivos: {', '.join(arquivos[:10])}"
    
    if "abrir pasta" in text:
        subprocess.Popen(f'explorer "{os.getcwd()}"')
        return "Pasta atual aberta"
    
    if "abrir bloco de notas" in text:
        subprocess.Popen("notepad.exe")
        return "Bloco de notas aberto"
    
    #comandos para abrir sites

    if "abrir google" in text:
        webbrowser.open("https://google.com")
        return "Abrindo google.com"

    if "abrir youtube" in text:
        webbrowser.open("https://www.youtube.com/")
        return "Abrindo youtube"
    
    if "abrir whatsapp" in text:
        webbrowser.open("https://web.whatsapp.com/")
        return "Abrindo whatsapp"
    
    if "abrir github" in text:
        webbrowser.open("https://github.com/")
        return "Abrindo github"
    
    if "abrir seu superior" in text:
        webbrowser.open("https://chatgpt.com/")
        return "Abrindo chatGPT"

    #informações uteis
    
    if "que dia é hoje" in text:
        from datetime import datetime
        agora = datetime.now().strftime("%d/%m/%Y")
        return f"Hoje é dia {agora}"
    
    if "que horas são" in text:
        from datetime import datetime
        agora = datetime.now().strftime("%H:%M:%S")
        return f"Agora são {agora}"
    
    #estatisticas do sistema e do Dogen
    
    if "sistema" in text:
        import platform
        import psutil
        import wmi
        from datetime import datetime
    
        # Informações básicas
        usuario = os.getenv('USERNAME', os.getenv('USER', 'desconhecido'))
        pasta_atual = os.getcwd()
        sistema = platform.system()
        versao = platform.release()
    
        # Memória
        memoria = psutil.virtual_memory()
        memoria_total = f"{memoria.total / (1024**3):.1f} GB"
        memoria_usada = f"{memoria.percent}%"
    
        # CPU
        cpu = platform.processor()
        cpu_uso = f"{psutil.cpu_percent(interval=0.1)}%"

        # GPU
        try:
            w = wmi.WMI()
            for gpu in w.Win32_VideoController():
                gpu_nome = gpu.Name
        except:
            gpu_nome = "GPU não detectada"
    
        # Disco
        disco = psutil.disk_usage('/')
        disco_livre = f"{disco.free / (1024**3):.1f} GB"
    
        # Data/Hora
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    
        return f"""
         INFORMAÇÕES DO SISTEMA

         Usuário: {usuario}
         Sistema: {sistema} {versao}
         CPU: {cpu_uso} em uso
         Processador: {cpu}
         GPU: {gpu_nome}
         RAM: {memoria_usada} usado de {memoria_total}
         Disco livre: {disco_livre}
         Data/Hora: {agora}
        """
    
    if "status" in text or "status ia" in text:
        import time
        import platform
        import psutil
        from datetime import datetime

    
        # Informações da IA
        pasta_atual = os.getcwd()
    
        # Ping (teste de conexão)
        try:
            import requests
            inicio = time.time()
            requests.get('https://www.google.com', timeout=0.3)
            ping = int((time.time() - inicio) * 1000)
            status_rede = f"{ping} ms (Online)"
        except:
            status_rede = "Falha (Offline)"
    
        # Memória usada pela IA
        processo = psutil.Process()
        memoria_ia = f"{processo.memory_info().rss / 1024**2:.1f} MB"
    
        # Modelo
        modelo = "mistral 7B"
    
        return f"""
         STATUS DA IA
         
         Nome: Dogen
         Modelo: {modelo}
         Linguagem: Python 3.10
         Pasta: {pasta_atual}
         Rede: {status_rede}
         Uso memória: {memoria_ia}
         CPU: {psutil.cpu_percent()}%
        """    
        
    return None
