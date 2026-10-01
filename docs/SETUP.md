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
   python -c "import whisper; whisper.load_model('small.en')"
   python -c "from TTS.api import TTS; TTS(model_name='tts_models/en/ljspeech/tacotron2-DDC')"
   ```

3. Inicie o Ollama localmente. Em outra janela, execute `python main.py`.

4. Aguarde Whisper e a voz local carregarem. Em **File → Model**, selecione um dos modelos Ollama instalados e escolha **Load selected model**; nenhum LLM é carregado automaticamente. Quando a ação terminar, clique em **Start recording** e depois em **Finish recording** para enviar o áudio. O Dogen usa o dispositivo padrão de entrada e saída. Para escolher outros dispositivos, edite `mic_device` / `speaker_device` em `settings.json` com os índices retornados por `python -m sounddevice`.

Após a preparação, o Dogen usa apenas o Ollama em `localhost:11434` e modelos instalados localmente. O menu **File → Model** mostra quais modelos estão residentes e a VRAM global que o Ollama reporta. Trocar o modelo descarrega o anteriormente ativado pelo Dogen; a retenção normal é de cinco minutos após o último pedido. A ação para descarregar outros modelos pede confirmação porque o servidor é compartilhado com outros aplicativos. Se Whisper não estiver em cache, o aplicativo mostra uma mensagem com este guia. O Coqui também precisa estar em cache antes do uso offline.

**GPU (opcional):** o `start.bat` instala PyTorch CPU por padrão. Para usar a GPU e acelerar TTS e Whisper, instale a versão CUDA manualmente após o setup:
```powershell
.venv\Scripts\python.exe -m pip install --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```
Substitua `cu121` pela versão do seu CUDA (`nvcc --version`). CUDA 12.1 cobre a maioria das GPUs RTX 30xx/40xx.

O pacote usado é `coqui-tts`, o fork mantido do Coqui. Ele conserva a importação `from TTS.api import TTS`. Não instale o pacote antigo `TTS` no mesmo ambiente virtual.

O primeiro carregamento dos modelos pode levar mais tempo. A duração de cada turno depende do hardware e da fala; os valores de latência na proposta original são metas, não garantias. `conversations.db` e `app.log` são gerados no diretório do projeto e ignorados pelo Git.

Rode `python -m pytest -q` para testar o código sem microfone ou modelos instalados.
