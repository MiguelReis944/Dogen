# Preparar o Dogen para uso local

1. Instale Python 3.10, Ollama e um microfone. Crie um ambiente virtual:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

2. Com internet **somente na preparação**, baixe os modelos uma vez:

   ```powershell
   ollama pull mistral
   python -c "import whisper; whisper.load_model('base')"
   python -c "from TTS.api import TTS; TTS(model_name='tts_models/en/ljspeech/tacotron2-DDC')"
   ```

3. Inicie o Ollama localmente. Em outra janela, execute `python main.py`.

4. Use **Start Recording** para iniciar uma conversa e **Stop** para encerrá-la. O Dogen usa o dispositivo padrão de entrada e saída. Para escolher outros dispositivos, edite `mic_device` e `speaker_device` em `settings.json` com os índices retornados por `python -m sounddevice`.

Após a preparação, o Dogen usa apenas o Ollama em `localhost:11434` e modelos instalados localmente. Se Whisper não estiver em cache, o aplicativo mostra uma mensagem com este guia. O Coqui também precisa estar em cache antes do uso offline.

O pacote usado é `coqui-tts`, o fork mantido do Coqui. Ele conserva a importação `from TTS.api import TTS`. Não instale o pacote antigo `TTS` no mesmo ambiente virtual.

O primeiro carregamento dos modelos pode levar mais tempo. A duração de cada turno depende do hardware e da fala; os valores de latência na proposta original são metas, não garantias. `conversations.db` e `app.log` são gerados no diretório do projeto e ignorados pelo Git.

Rode `python -m pytest -q` para testar o código sem microfone ou modelos instalados.
