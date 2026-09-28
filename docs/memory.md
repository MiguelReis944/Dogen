# Memória do projeto

## Fatos e decisões

- Padrões atuais: Whisper `small.en`, Ollama `mistral`, Coqui LJSpeech e VAD adaptativo.
- O histórico fica em `conversations.db`; sessões retomam o contexto do mesmo dia.
- O contexto de conversa mantém dez pares por padrão.

## Armadilhas conhecidas

O relatório de release diz que a implementação está completa, mas a aceitação humana
continua pendente. Não chame o produto de validado até resolver essas linhas e preserve
a distinção entre métricas de atividade, desempenho e retenção.
