# Memória do projeto

## Fatos e decisões

- Padrões atuais: Whisper `small.en`, Ollama `mistral`, Coqui LJSpeech e VAD adaptativo.
- O histórico fica em `conversations.db`; sessões retomam o contexto do mesmo dia.
- O contexto de conversa mantém dez pares por padrão.
- A tela principal prioriza conversa: Today é passivo e a meta de gravação é configurável
  em Settings (15 minutos por padrão), baseada nos frames realmente capturados; Fixes é
  somente leitura; volume aparece durante gravação.
- A revisão da transcrição é ativada por padrão; Settings oferece envio automático em
  10, 15 ou 30 segundos, ou revisão manual sem envio automático. A captura ainda tem um
  teto de 60 segundos por fala; ele é independente do contexto do Ollama.
- O modo Fluency muda o estilo conversacional, mas não desativa correções de erros
  significativos em inglês. Fixes mostra texto breve, sem controles de correção; não se
  inventam correções para frases naturais.
- Anotações como Grammar, Agreement e Note são removidas antes da exibição e narração,
  inclusive quando chegam em pedaços. Fixes rejeita equivalências de contração,
  pontuação e algumas sugestões de estilo; a frase citada precisa aparecer na
  transcrição do turno. Isso não garante que o modelo identifique todo erro real nem
  distingue com certeza um erro do Whisper de um erro de inglês.
- A voz usa áudio float em memória e prepara chunks antes do fim da reprodução
  anterior. O WAV normalizado por pico e a segunda divisão de frases do Coqui
  amplificavam artefatos e acrescentavam pausas.
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

No bundle Windows do PyInstaller, Coqui precisa dos arquivos-fonte em
`TTS/vocoder/configs` porque lista essa pasta durante a importação. O pacote
`ko_speech_tools` também exige os recursos do namespace `ko_speech_tools.data` usados
por `importlib.resources`. O verificador do build compara os recursos relativos ao
pacote instalado no ambiente de build com o bundle, sem depender do caminho daquela
máquina. `TTS.vocoder.layers.wavegrad` também deve ser extraído como fonte: o módulo
define funções `torch.jit.script`, cujo import precisa ler o `.py` fisicamente. O build
verifica e executa esse módulo no arquivo extraído para detectar omissões ou corrupção.

Falhas de carregamento detectadas pelo worker deixam a mensagem e permitem `Retry loading`
depois de corrigir a causa; falhas de um turno voltam ao modo de gravação e preservam o
texto de diagnóstico até a próxima tentativa. A verificação inicial de microfone em
`main.py` acontece antes de abrir a janela; se ela falhar, é preciso corrigir o dispositivo
ou a permissão e reiniciar o Dogen.
