import os
import subprocess


async def handle_command(text):

    if "crie uma pasta" in text:
        # Remove a parte "crie uma pasta" do texto
        name = text.replace("crie uma pasta", "").strip()
        name = name.replace("chamada", "").strip()
        name = name.replace("com o nome", "").strip()
        name = name.replace("de nome", "").strip()
    
        # Se não sobrou nada, usa nome padrão
        if not name:
            name = "Nova Pasta"
    
        os.makedirs(name, exist_ok=True)
        return f"Pasta '{name}' criada"

    if "abra code" in text:
        subprocess.Popen("code")
        return "Abrindo VS Code"
    
    if "abra música" in text:
        caminho = r"C:\Users\Pichau\AppData\Roaming\Spotify\Spotify.exe"
        subprocess.Popen([caminho])
        return "Abrindo Spotify"
    
    if "abra as notas" in text:
        subprocess.Popen("notepad.exe")
        return "Bloco de notas aberto"

    if "abra a pasta" in text:
        subprocess.Popen(f'explorer "{os.getcwd()}"')
        return "Pasta atual aberta"
    
    if "liste arquivos" in text:
        arquivos = os.listdir()
        return f"Arquivos: {', '.join(arquivos[:10])}"
    
    if "sistema" in text:
        import platform
        import psutil
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
         RAM: {memoria_usada} usado de {memoria_total}
         Disco livre: {disco_livre}
         Data/Hora: {agora}
        """
    
    if "status" in text or "status ia" in text:
        import time
        import platform
        import psutil
        from datetime import datetime
        from assistant import numero_comandos
    
        # Informações da IA
        comandos_executados = numero_comandos
        pasta_atual = os.getcwd()
    
        # Ping (teste de conexão)
        try:
            import requests
            inicio = time.time()
            requests.get('https://www.google.com', timeout=0.3)
            ping = int((time.time() - inicio) * 1000)
            status_rede = f"{ping} ms ( Online)"
        except:
            status_rede = "Falha ( Offline)"
    
        # Memória usada pela IA
        processo = psutil.Process()
        memoria_ia = f"{processo.memory_info().rss / 1024**2:.1f} MB"
    
        # Modelo
        modelo = "mistral 7B"
    
        return f"""
         STATUS DA IA
         
         Modelo: {modelo}
         Linguagem: Python 3.10)
         Pasta: {pasta_atual}
         Comandos: {comandos_executados}
         Rede: {status_rede}
         Memória: {memoria_ia}
         CPU: {psutil.cpu_percent()}%
        """    
        
    return None
