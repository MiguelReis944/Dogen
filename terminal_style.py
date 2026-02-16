# terminal_style.py
"""
Módulo para estilizar o terminal APENAS neste projeto
Não altera as configurações globais do VS Code
"""

class Cores:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    ITALIC = '\033[3m'
    VERDE = '\033[32m'
    AZUL = '\033[34m'
    AMARELO = '\033[33m'

    @staticmethod
    def usuario(texto):
        """Formata a mensagem do usuário."""
        linhas = texto.split('\n')

        formatado = f"{Cores.VERDE}{Cores.BOLD}Você:{Cores.RESET}\n"

        for linha in linhas:
            formatado += f"   {Cores.ITALIC}{linha}{Cores.RESET}\n"

        return formatado


    @staticmethod
    def assistente(texto):
        """Formata a mensagem do assistente V."""
        linhas = texto.split('\n')

        formatado = f"{Cores.AZUL}{Cores.BOLD}Dogen:{Cores.RESET}\n"

        for linha in linhas:
            formatado += f"   {Cores.AMARELO}{linha}{Cores.RESET}\n"

        return formatado


