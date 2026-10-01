# Requisitos do produto

## Problema e pessoas usuárias

Pessoas que aprendem inglês precisam praticar conversa com feedback útil sem enviar
áudio, transcrições ou histórico para um serviço remoto.

## Escopo atual

Dogen é um coach conversacional desktop offline. Ele captura voz, transcreve com
Whisper, conversa com um modelo Ollama local, sintetiza a resposta com Coqui TTS e
persiste o histórico em SQLite.

## Requisitos

- Iniciar com diagnósticos acionáveis para microfone, modelos e Ollama ausentes.
- Permitir gravação manual por clique, revisão da transcrição ativada por padrão, envio
  automático após 10, 15 ou 30 segundos ou confirmação manual sem prazo, e cancelamento.
- Explicar cada configuração com ajuda contextual acessível junto ao controle.
- Responder em inglês com uma correção breve para cada erro significativo, separada do diálogo e exibida como texto somente de leitura. Não inventar correções para frases naturais.
- Restaurar a sessão do dia e oferecer replay/stop sem criar turnos extras.
- Mostrar progresso sem chamar atividade de proficiência ou inventar nota de pronúncia.
- Permitir configurar a meta diária de gravação, com padrão de 15 minutos e persistência
  local em `settings.json`.
- Consultar os modelos Ollama instalados e exigir uma escolha explícita antes de carregar
  um LLM. Mostrar separadamente seleção atual, modelo usado na última resposta e a lista
  global de modelos residentes/VRAM reportada pelo Ollama.
- Permitir ajustar manualmente o tamanho do texto de Conversa, Today e Fixes entre 12 e 24
  px, com padrão de 15 px e persistência local.

## Critérios de aceitação e evidências

O README, `docs/quality/daily-practice-release-report.md` e a suíte existente registram
o comportamento implementado. A aceitação humana pendente continua explícita no
relatório de release.

## Fora de escopo

Nuvem obrigatória, múltiplos perfis, pontuação fonética não validada e tratar a
atividade como domínio de proficiência estão fora do produto atual.
