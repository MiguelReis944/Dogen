# Arquitetura atual

## Componentes e limites

`main.py` inicializa a aplicação; `ui/` contém PyQt5 e o worker em `QThread`; `audio/`
captura, detecta voz e reproduz; `nlp/` integra Whisper, Ollama e Coqui; `storage/`
grava SQLite; `pipeline.py` orquestra o turno e o cancelamento; `utils/` lê configurações.

## Fluxos de dados e controle

O fluxo principal é `microfone → VAD → Whisper → Ollama/Mistral → Coqui TTS → player`.
Um turno completo grava mensagens em `conversations.db` e mantém até dez pares de
contexto, conforme `context_size`.

## Interfaces

As interfaces são sinais PyQt5, callbacks de cancelamento, `settings.json`, SQLite e
as APIs locais do Whisper, Ollama e Coqui. Não há serviço remoto necessário para o
fluxo de produto.

## Decisões técnicas vigentes

Gravação usa cliques para começar e terminar; revisão de transcrição tem timeout de
cinco segundos; a voz TTS exposta é a feminina local. A direção futura do domínio está
em `docs/design/2026-09-27-learning-system-design.md`, não substitui a implementação.
