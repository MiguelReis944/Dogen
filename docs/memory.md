# Memória do projeto

## Fatos e decisões

- Padrões atuais: Whisper `small.en`, Ollama `mistral`, Coqui LJSpeech e VAD adaptativo.
- O histórico fica em `conversations.db`; sessões retomam o contexto do mesmo dia.
- O contexto de conversa mantém dez pares por padrão.
- A tela principal prioriza conversa: Today é passivo, exibe meta aproximada de 15
  minutos e métricas locais; Fixes é somente leitura; volume aparece durante gravação.
- O cálculo diário de minutos é uma estimativa entre o primeiro e o último turno
  concluído, não tempo de fala medido pelo microfone.

## Armadilhas conhecidas

O relatório de release diz que a implementação está completa, mas a aceitação humana
continua pendente. Não chame o produto de validado até resolver essas linhas e preserve
a distinção entre métricas de atividade, desempenho e retenção.
