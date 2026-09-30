# Memória do projeto

## Fatos e decisões

- Padrões atuais: Whisper `small.en`, Ollama `mistral`, Coqui LJSpeech e VAD adaptativo.
- O histórico fica em `conversations.db`; sessões retomam o contexto do mesmo dia.
- O contexto de conversa mantém dez pares por padrão.
- A tela principal prioriza conversa: Today é passivo e a meta de gravação é configurável
  em Settings (15 minutos por padrão), baseada nos frames realmente capturados; Fixes é
  somente leitura; volume aparece durante gravação.
- Palavras e fillers são estimados a partir da transcrição final enviada ao coach, que pode
  ter sido editada; o streak conta dias com tentativa do usuário, mesmo se a resposta for
  interrompida.
- A duração não inclui pausas entre turnos nem processamento. Sessões antigas não têm
  duração gravada e não recebem estimativa retroativa.
- Respostas interrompidas ficam marcadas no histórico, mas não entram no contexto futuro
  nem nas métricas de turnos concluídos.

## Armadilhas conhecidas

O relatório de release diz que a implementação está completa, mas a aceitação humana
continua pendente. Não chame o produto de validado até resolver essas linhas e preserve
a distinção entre métricas de atividade, desempenho e retenção.
