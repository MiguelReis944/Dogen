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
- Permitir gravação manual por clique, revisão opcional da transcrição e cancelamento.
- Responder em inglês com correções e sugestões de frase separadas do diálogo.
- Restaurar a sessão do dia e oferecer replay/stop sem criar turnos extras.
- Mostrar progresso sem chamar atividade de proficiência ou inventar nota de pronúncia.

## Critérios de aceitação e evidências

O README, `docs/quality/daily-practice-release-report.md` e a suíte existente registram
o comportamento implementado. A aceitação humana pendente continua explícita no
relatório de release.

## Fora de escopo

Nuvem obrigatória, múltiplos perfis, pontuação fonética não validada e tratar a
atividade como domínio de proficiência estão fora do produto atual.
