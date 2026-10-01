# Arquitetura atual

## Componentes e limites

`main.py` inicializa a aplicação; `ui/` contém PyQt5 e o worker em `QThread`; `audio/`
captura, detecta voz e reproduz; `nlp/` integra Whisper, Ollama e Coqui; `storage/`
grava SQLite; `pipeline.py` orquestra o turno e o cancelamento; `utils/` lê configurações.

## Fluxos de dados e controle

O fluxo principal é `microfone → VAD → Whisper → Ollama/Mistral → Coqui TTS → player`.
Um turno completo grava mensagens, feedback estruturado e métricas em
`conversations.db`, e mantém até dez pares de contexto, conforme `context_size`.
Áudio capturado é registrado separadamente para medir tempo de microfone sem incluir
intervalos ou processamento. Respostas de streaming interrompidas ficam marcadas no
histórico, mas são excluídas da restauração do contexto e dos turnos concluídos. Dias e
streaks de prática contam tentativas do usuário; `completed_turns` continua contando
somente respostas completas.

## Interfaces

As interfaces são sinais PyQt5, callbacks de cancelamento, `settings.json`, SQLite e
as APIs locais do Whisper, Ollama e Coqui. `daily_recording_goal_minutes` configura a
meta do Today, com padrão de 15 minutos para arquivos de configuração existentes.
`practice_font_size_px` configura o tamanho do texto de Conversa, Today e Fixes entre 12 e
24 px, com padrão de 15 px para configurações existentes. Não há serviço remoto necessário
para o fluxo de produto.

Diagnósticos de confiabilidade são locais e opcionais (`diagnostics_enabled`, desligado
por padrão). Quando ativados, escrevem eventos com campos permitidos na pasta de dados
locais do usuário, em um log rotativo limitado a 512 KB e duas cópias. Desativar a opção
remove o handler imediatamente; conteúdo de áudio, transcrições, respostas e segredos não
fazem parte do esquema de eventos. Um identificador aleatório de 128 bits correlaciona
somente as durações das etapas e o resultado de persistência de um turno.

## Decisões técnicas vigentes

Gravação usa cliques para começar e terminar, com limite de segurança atual de 60
segundos por captura. Whisper só recebe o áudio depois que a captura termina; em seguida
o texto transcrito é enviado ao Ollama. O modelo é aquecido na inicialização e mantido
carregado. A revisão da transcrição vem ativada por padrão e pode enviar automaticamente
após 10, 15 ou 30 segundos, ou aguardar confirmação manual. A voz TTS exposta é a feminina
local. A direção futura do domínio está
em `docs/design/2026-09-27-learning-system-design.md`, não substitui a implementação.

O Ollama recebe texto, não a gravação. O contexto de geração está fixado em 4.096 tokens;
esse espaço é compartilhado pelas instruções, histórico, transcrição atual e resposta.
O parâmetro de máximo de tokens gerados não é enviado pelo cliente.

A resposta em streaming remove anotações de coaching antes de segmentar frases ou
exibi-las. Fixes recebe somente pares de correção vinculados à transcrição do turno;
categorias ficam como metadados internos. O histórico persistido continua intacto,
mas anotações antigas são omitidas na conversa e no contexto enviado ao modelo.

A síntese obtém áudio float em memória, sem normalização por pico de arquivo WAV e
sem repetir a segmentação interna do Coqui. Uma fila limitada a dois chunks prepara
a próxima frase durante a reprodução atual, inclusive em Replay. Acesso à síntese é
serializado entre produtores interrompidos e novos turnos. Saídas não finitas,
silenciosas, com formato inválido ou duração excessiva são rejeitadas; uma falha de
áudio preserva a resposta em texto.
