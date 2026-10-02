# Dogen

Coach de inglês conversacional, 100% offline. Captura a sua voz, transcreve com Whisper, responde via Ollama e fala de volta com Coqui TTS — tudo no seu computador, sem nuvem.

## Início rápido

Para desenvolvimento local, execute `start.bat`. Na primeira vez, cria o virtualenv, instala as dependências e verifica os modelos de fala. Nas vezes seguintes, verifica o cache e abre direto.

```
start.bat
```

Para testar sem Python ou `.bat`, use o instalador Windows em `packaging/README.md`.
Ele instala o Dogen e abre um guia inicial para preparar os modelos de fala e
conectar um modelo local do Ollama. O Ollama e os pesos dos modelos continuam
separados; conversas e configurações ficam em `%LOCALAPPDATA%\Dogen` e não são
apagadas ao desinstalar o aplicativo. O guia de empacotamento também documenta a
recuperação de instalações antigas que falham ao verificar a voz local.

Para setup manual, veja [docs/SETUP.md](docs/SETUP.md).

Ao abrir, Dogen maximiza a janela e carrega automaticamente Whisper e a voz local. Ele consulta os modelos instalados do Ollama, mas não carrega um LLM por conta própria: em **File → Model**, confira a última escolha (ou escolha outro modelo) e selecione **Load selected model**. Quando o carregamento terminar, use **Start recording** e depois **Finish recording** para enviar a fala.

O menu **Model** distingue o modelo selecionado, o que Dogen usará na próxima resposta, o modelo usado na última resposta e os modelos que o Ollama mantém residentes. O uso de VRAM é global ao Ollama e pode incluir outros aplicativos. Ao trocar, Dogen descarrega o modelo que ele ativou antes de carregar o novo; chamadas mantêm o modelo por até cinco minutos de inatividade. **Unload other models and load selected…** pode liberar modelos residentes antigos, mas pede confirmação porque afeta todos os aplicativos conectados ao Ollama.

## Prática diária

O modo de gravação é controlado por cliques: um clique começa e outro termina. Isso evita que uma pausa natural corte a frase e não exige segurar uma tecla. A barra ao lado do botão mostra o volume captado; durante o carregamento, o mesmo espaço explica o que Dogen está preparando.

A conversa ocupa o painel principal. **Fixes** mostra correções e frases alternativas sem poluir o diálogo, e **Status** mostra o estágio atual. Ações secundárias, seleção de cenário e seleção de modelo ficam no menu **File**. A narração usa somente a voz feminina local.

Em **Settings**, **Review transcript before sending** vem ativado por padrão para você conferir e editar o texto reconhecido antes de enviá-lo ao coach. Você pode escolher o envio automático depois de 10, 15 ou 30 segundos, ou selecionar **Never** para confirmar manualmente. Também há um ícone de ajuda ao lado das opções para explicar cada configuração.

Depois de uma resposta completa, use **Replay response** para ouvi-la novamente ou **Stop audio** para interromper a fala. Repetir uma resposta não cria outro turno, não chama o Ollama e não altera as estatísticas.

## Pipeline de um turno

```
microfone → VAD adaptativo → Whisper (small.en) → Ollama/modelo selecionado
  → Coqui TTS (por sentença) → reprodução
```

## Feedback de coaching

O Dogen responde em inglês e, quando detecta um erro significativo, acrescenta uma correção breve em qualquer modo de conversa:

```
[Correction: I go to school yesterday → I went to school yesterday]
```

As correções aparecem como texto curto e somente leitura no painel **Fixes**. Fluency
mode muda o estilo da conversa, mas não desativa as correções. Comentários de Grammar,
Agreement e outras anotações não aparecem na conversa nem são narrados. O filtro rejeita
mudanças somente de contração, pontuação e algumas preferências de estilo, e confere se
o trecho citado pertence à transcrição do turno. A qualidade restante depende do modelo
local; a transcrição do Whisper também pode conter erros.

A voz prepara a próxima frase durante a reprodução atual, sem a segunda divisão de
frases e a normalização por pico de WAV do Coqui. Áudio inválido ou excessivamente longo
gera uma indicação de falha; a resposta em texto continua salva e disponível.

## Sessões

Cada dia começa uma sessão nova. Dentro do mesmo dia, retomar o app continua de onde parou — contexto e histórico são restaurados automaticamente. O histórico fica em `conversations.db`: no diretório do projeto ao executar pelo código-fonte e em `%LOCALAPPDATA%\Dogen` na versão instalada.

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
| `ollama_model` | `mistral` | preferência inicial para seleção; o último modelo escolhido fica salvo localmente |
| `whisper_model` | `base` | modelo Whisper inicial para uma configuração nova; pode ser alterado em Settings |
| `tts_model` | `tts_models/en/ljspeech/tacotron2-DDC` | voz feminina fixa do Coqui TTS |
| `vad_threshold` | `0.02` | sensibilidade base do detector de voz |
| `silence_duration_sec` | `2.0` | valor legado preservado para compatibilidade de configuração |
| `input_mode` | `ptt` | valor legado; a interface usa gravação manual por cliques |
| `review_transcript` | `true` | permite conferir e editar a transcrição antes de enviá-la; configs existentes com `false` continuam desativadas |
| `review_transcript_auto_send_seconds` | `15` | envia a transcrição revisada após 10, 15 ou 30 segundos; `null` significa **Never** (confirmação manual) |
| `noise_reduction` | `true` | aplica redução de ruído depois da captura; pode ser desligada para comparar clareza |
| `diagnostics_enabled` | `false` | grava eventos locais de confiabilidade, sem áudio nem transcrições |
| `context_size` | `10` | pares de mensagens mantidos em contexto |

Os valores da tabela são os padrões usados quando ainda não existe um arquivo de
configuração do usuário. Ao executar pelo código-fonte, o Dogen também lê
`settings.json` na raiz do repositório, que pode sobrescrever esses valores; no
instalador, as preferências ficam em `%LOCALAPPDATA%\Dogen\settings.json`. Por exemplo,
o arquivo atualmente versionado no checkout usa `small.en`, 20 pares de contexto e
desativa a revisão da transcrição.

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
