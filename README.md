# V - Assistente Pessoal Offline

**V** é um assistente pessoal inteligente que funciona **100% offline** no seu computador.
Ele conversa naturalmente, entende comandos e responde com uma voz amigável — tudo rodando localmente, sem depender da internet.

---

## ✨ Características

* 🎤 **Reconhecimento de Voz**
  Entende comandos em português e inglês.

* 🤖 **IA Local**
  Utiliza o modelo Mistral rodando localmente através do Ollama.

* 🔊 **Síntese de Voz Offline**
  Responde com uma voz natural sem precisar de conexão com servidores externos.

* ⚡ **Privacidade Total**
  Todos os dados e conversas permanecem no seu computador.

* 💬 **Conversa Natural**
  Capaz de manter contexto e responder de forma informal e amigável.

---

## 🖥️ Requisitos

* Python 3.8 ou superior
* Microfone funcionando
* Ollama instalado com o modelo Mistral 7B

---

## 📦 Instalação

# Nome do Projeto (V)

[Breve descrição do que o projeto faz]

## Pré-requisitos

Antes de começar, você vai precisar ter o Python instalado em sua máquina.

## Instalação e Execução

Para garantir que todas as dependências sejam instaladas corretamente sem conflitos, é **necessário** utilizar um ambiente virtual (`venv`).

### 1. Clonar o repositório
```bash
git clone [https://github.com/MiguelReis944/V.git](https://github.com/MiguelReis944/V.git)
cd V
```

---

### 2. Criar o ambiente virtual

```bash
# No Windows:
python -m venv venv

# No Linux/macOS:
python3 -m venv venv
```

---

### 3. Instale as dependências do Python

```bash
# No Windows (Command Prompt):
venv\Scripts\activate

# No Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# No Linux/macOS:
source venv/bin/activate
```

---

### 4. Instale as dependências do Python

```bash
pip install -r requirements.txt
```

---

### 5. Instale o Ollama

Baixe e instale através do site oficial.

Depois de instalar, execute o seguinte comando para baixar o modelo de IA:

```bash
ollama pull mistral
```

---

### 6. Execute o assistente

```bash
python assistant.py
```

Pronto!
O **V** já estará ouvindo seus comandos 🎧

---

## 🗣️ Comandos Disponíveis

* **"crie uma pasta chamada [nome]"**
  Cria uma nova pasta no diretório atual.

* **"abra o vs code"**
  Abre o editor Visual Studio Code.

* Para qualquer outro comando, o **V** responderá utilizando IA e linguagem natural.

---

## 📁 Estrutura do Projeto

| Arquivo              | Função                               |
| -------------------- | ------------------------------------ |
| `assistant.py`       | Loop principal do assistente         |
| `ai_response.py`     | Comunicação com o modelo de IA local |
| `speech_to_text.py`  | Conversão de fala para texto         |
| `text_to_speech.py`  | Conversão de texto para fala         |
| `command_handler.py` | Execução de comandos específicos     |

---

## 📚 Dependências Utilizadas

* **ollama**
  Comunicação com o modelo de IA local.

* **SpeechRecognition**
  Responsável pelo reconhecimento de voz
  (por padrão utiliza serviços do Google, mas pode ser configurado para offline).

* **pyttsx3**
  Síntese de voz totalmente offline.

---

## ⚙️ Notas

* O assistente está configurado para chamar o usuário de **Reis**.
* O histórico de conversa é mantido para melhorar o contexto das respostas.
* Todo o processamento é feito localmente, garantindo maior privacidade.
* O reconhecimento de voz pode ser configurado para funcionar totalmente offline, se desejado.

---

## 🔒 Privacidade

Nenhum dado é enviado para a internet durante o uso da IA local.
Todo o processamento acontece diretamente na sua máquina.

---

**V — Seu assistente pessoal, rápido, inteligente e privado.**

