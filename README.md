# Dogen

Coach de inglês conversacional, 100% offline. Captura a sua voz, transcreve com Whisper, responde via Ollama e fala de volta com Coqui TTS — tudo no seu computador, sem nuvem.

## Início rápido

Execute `start.bat`. Na primeira vez, cria o virtualenv, instala as dependências e baixa os modelos (Whisper, Coqui TTS, Ollama/Mistral). Nas vezes seguintes, verifica o cache e abre direto.

```
start.bat
```

Para setup manual, veja [docs/SETUP.md](docs/SETUP.md).

Ao abrir, Dogen maximiza a janela e carrega automaticamente Whisper, a voz local e o modelo do Ollama. As etapas aparecem na região do medidor; a gravação não começa sozinha. Quando **Start recording** for liberado, clique para começar a falar e depois em **Finish recording** para enviar.

## Prática diária

O modo de gravação é controlado por cliques: um clique começa e outro termina. Isso evita que uma pausa natural corte a frase e não exige segurar uma tecla. A barra ao lado do botão mostra o volume captado; durante o carregamento, o mesmo espaço explica o que Dogen está preparando.

A conversa ocupa o painel principal. **Fixes** mostra correções e frases alternativas sem poluir o diálogo, e **Status** mostra o estágio atual. Ações secundárias, seleção de cenário e seleção de modelo ficam no menu **File**. A narração usa somente a voz feminina local.

Em **Settings**, ative **Review transcript before sending** para corrigir o texto reconhecido antes de enviá-lo ao coach; a revisão é enviada automaticamente depois de 15 segundos se você não confirmar antes.

Depois de uma resposta completa, use **Replay response** para ouvi-la novamente ou **Stop audio** para interromper a fala. Repetir uma resposta não cria outro turno, não chama o Ollama e não altera as estatísticas.

## Pipeline de um turno

```
microfone → VAD adaptativo → Whisper (small.en) → Ollama/Mistral
  → Coqui TTS (por sentença) → reprodução
```

## Feedback de coaching

O Dogen responde em inglês e, quando detecta um erro significativo, acrescenta uma correção breve em qualquer modo de conversa:

```
[Correction: I go to school yesterday → I went to school yesterday]
```

As correções aparecem como texto curto e somente leitura no painel **Fixes**. Fluency mode muda o estilo da conversa, mas não desativa as correções. O Dogen não inventa correções para inglês natural.

## Sessões

Cada dia começa uma sessão nova. Dentro do mesmo dia, retomar o app continua de onde parou — contexto e histórico são restaurados automaticamente. O histórico fica em `conversations.db`, no diretório do projeto.

## Progresso local

Abra **File → Progress…** para consultar os últimos 7 ou 30 dias. As métricas são calculadas localmente:

- um dia de prática é um dia com pelo menos um turno concluído;
- `fillers / 100 words` = fillers detectados ÷ palavras persistidas × 100;
- `Transcripts you edited` = transcrições alteradas na revisão ÷ turnos com métricas;
- tempo de prática soma apenas os frames de áudio capturados enquanto o microfone está
  gravando; pausas de processamento e intervalos entre turnos não entram na conta;
- categorias contam apenas correções estruturadas produzidas pelo coach.

Sessões antigas continuam contando como atividade, mas não têm duração retroativa de
gravação e não entram nos minutos registrados. Elas aparecem como **Not enough data**
em taxas que ainda não eram armazenadas. O Dogen não mostra nota de pronúncia, fluência
ou proficiência porque essas medidas exigem um avaliador fonético validado; atividade e
opinião do LLM não são substitutos honestos.

## Configuração (`settings.json`)

| Chave | Padrão | Descrição |
|---|---|---|
| `ollama_model` | `mistral` | modelo LLM no Ollama |
| `whisper_model` | `small.en` | modelo Whisper (english-only, melhor precisão) |
| `tts_model` | `tts_models/en/ljspeech/tacotron2-DDC` | voz feminina fixa do Coqui TTS |
| `vad_threshold` | `0.02` | sensibilidade base do detector de voz |
| `silence_duration_sec` | `2.0` | valor legado preservado para compatibilidade de configuração |
| `input_mode` | `ptt` | valor legado; a interface usa gravação manual por cliques |
| `review_transcript` | `false` | permite editar a transcrição antes de enviá-la |
| `noise_reduction` | `true` | aplica redução de ruído depois da captura; pode ser desligada para comparar clareza |
| `diagnostics_enabled` | `false` | grava eventos locais de confiabilidade, sem áudio nem transcrições |
| `context_size` | `10` | pares de mensagens mantidos em contexto |

O registro opcional de confiabilidade pode ser ligado em **Settings → Privacy**. Ele fica
na pasta de dados locais do usuário como `diagnostics.log`, é limitado a 512 KB mais duas
cópias rotacionadas e registra apenas estados, durações, motivo de parada, tipo de erro e
um identificador aleatório por turno — nunca áudio, texto da conversa, respostas do modelo
ou chaves. Desligar a opção interrompe novas gravações no log imediatamente.

Para dispositivos de áudio específicos, rode `python -m sounddevice` para listar os índices e edite `mic_device` / `speaker_device`.

Para comparar modelos com gravações privadas, crie `local-evaluation/manifest.json` conforme o protocolo em `docs/quality/daily-practice-baseline.md` e execute:

```powershell
python scripts/evaluate_transcription.py --manifest local-evaluation/manifest.json --model small.en --output small-clean.evaluation.json
python scripts/evaluate_transcription.py --manifest local-evaluation/manifest.json --model small.en --no-noise-reduction --output small-raw.evaluation.json
```

Os áudios e relatórios `*.evaluation.json` são ignorados pelo Git.

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
