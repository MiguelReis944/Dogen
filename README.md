# Dogen

Dogen é um aplicativo desktop local para praticar inglês por conversa falada. Ele captura a voz do usuário, transcreve com Whisper, envia a conversa a um modelo no Ollama e reproduz a resposta sintetizada pelo Coqui TTS. Durante a conversa, mostra a transcrição e a resposta na janela PyQt5.

O processamento funciona sem serviços externos depois que as dependências e os modelos são instalados. O histórico fica em `conversations.db`, no próprio computador.

## Início rápido

Veja [docs/SETUP.md](docs/SETUP.md) para instalar Python 3.10, Ollama, Mistral, Whisper e Coqui TTS. Depois execute:

```powershell
python main.py
```

Clique em **Start Recording** para iniciar a sessão. Dogen encerra cada fala após dois segundos de silêncio e começa a gravar o turno seguinte após responder. **Stop** interrompe a sessão; uma operação de inferência já iniciada pode levar alguns segundos para terminar.

## Estrutura

- `main.py`: inicialização e validação do microfone.
- `ui/`: janela PyQt5 e sinais da thread de trabalho.
- `audio/`: captura, detecção de silêncio e reprodução.
- `nlp/`: Whisper, Ollama e Coqui TTS.
- `pipeline.py`: ordem de processamento de um turno.
- `storage/`: mensagens e preferências em SQLite.
- `utils/`: configuração JSON.
- `tests/`: testes locais sem hardware ou modelos grandes.

`settings.json` configura modelo, dispositivos de áudio, tempo de silêncio e limite de contexto. O contexto em memória contém até 10 pares recentes de mensagens. O banco é atualizado a cada turno concluído.
