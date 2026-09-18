# Dogen

Coach de inglês conversacional, 100% offline. Captura a sua voz, transcreve com Whisper, responde via Ollama e fala de volta com Coqui TTS — tudo no seu computador, sem nuvem.

## Início rápido

Execute `start.bat`. Na primeira vez, cria o virtualenv, instala as dependências e baixa os modelos (Whisper, Coqui TTS, Ollama/Mistral). Nas vezes seguintes, verifica o cache e abre direto.

```
start.bat
```

Para setup manual, veja [docs/SETUP.md](docs/SETUP.md).

Clique em **Start Recording** para começar. Dogen encerra o seu turno após ~1,3 s de silêncio e começa a responder imediatamente — a primeira sentença toca enquanto as demais são sintetizadas. **Stop** interrompe a sessão; uma inferência já iniciada pode levar alguns segundos para terminar.

## Pipeline de um turno

```
microfone → VAD adaptativo → Whisper (small.en) → Ollama/Mistral
  → Coqui TTS (por sentença) → reprodução
```

## Feedback de coaching

O Dogen responde em inglês e, quando detecta erros, acrescenta ao final:

```
[Correction: I go to school yesterday → I went to school yesterday]
[Better phrasing: "I had class yesterday" sounds more natural]
```

Correções aparecem em laranja e sugestões em verde na janela de conversa.

## Sessões

Cada dia começa uma sessão nova. Dentro do mesmo dia, retomar o app continua de onde parou — contexto e histórico são restaurados automaticamente. O histórico fica em `conversations.db`, no diretório do projeto.

## Configuração (`settings.json`)

| Chave | Padrão | Descrição |
|---|---|---|
| `ollama_model` | `mistral` | modelo LLM no Ollama |
| `whisper_model` | `small.en` | modelo Whisper (english-only, melhor precisão) |
| `tts_model` | `tts_models/en/ljspeech/tacotron2-DDC` | voz Coqui TTS |
| `vad_threshold` | `0.02` | sensibilidade base do detector de voz |
| `silence_duration_sec` | `1.3` | segundos de silêncio para encerrar o turno |
| `context_size` | `10` | pares de mensagens mantidos em contexto |

Para dispositivos de áudio específicos, rode `python -m sounddevice` para listar os índices e edite `mic_device` / `speaker_device`.

**Voz mais natural:** troque `tts_model` por `tts_models/multilingual/multi-dataset/xtts_v2` e execute `python -c "from TTS.api import TTS; TTS('tts_models/multilingual/multi-dataset/xtts_v2')"` para baixar o modelo.

## Estrutura

```
main.py          inicialização e validação do microfone
pipeline.py      orquestra os 4 estágios com suporte a cancelamento
ui/              janela PyQt5 e worker de background (QThread)
audio/           captura (VAD adaptativo), player interruptível
nlp/             Whisper, Ollama (streaming) e Coqui TTS (por sentença)
storage/         SQLite — mensagens e preferências
utils/           leitura de settings.json
docs/SETUP.md    instalação de dependências e modelos
```

## Testes

```powershell
python -m pytest -q
```

Não requerem microfone nem modelos instalados.
