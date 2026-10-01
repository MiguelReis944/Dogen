# Design de interação

## Jornadas de uso

Na abertura, Dogen carrega Whisper e a voz local e lista os modelos Ollama instalados,
sem aquecer um LLM automaticamente. A última escolha fica pré-selecionada em
**File → Model**; a pessoa pode alterá-la enquanto os componentes de fala carregam e,
quando estiverem prontos, escolhe **Load selected model**. Depois clica em Start
recording, fala, clica em Finish recording, acompanha a resposta e pode revisar a
transcrição antes do envio. Depois pode ouvir novamente ou parar o áudio.

## Interação e comportamento

O painel principal mostra conversa; `Fixes` separa correções breves e somente leitura.
Correções de erros reais aparecem em todos os modos e cenários, sem ações para repetir,
explicar ou pular a correção.
`Status` mostra carregamento e estágio. `File` concentra cenário, modelo e progresso;
`File → Model` mostra separadamente o modelo selecionado, o modelo que Dogen usará na
próxima resposta, o modelo usado na última resposta e os modelos residentes/VRAM
reportados pelo Ollama. A memória indicada é global ao serviço. A troca descarrega o
modelo ativado anteriormente pelo Dogen; a retenção normal é de cinco minutos depois da
última solicitação. **Unload other models and load selected…** é uma ação confirmada e
avisa que descarregar modelos residentes pode afetar outros aplicativos que usam Ollama.
`Settings` contém revisão de transcrição, opções de captura, a meta de gravação diária
exibida em Today (15 minutos por padrão) e o tamanho manual do texto de Conversa, Today e
Fixes (12–24 px, 15 px por padrão). Today mostra o tempo de áudio capturado numa única
linha; contagens de palavras e fillers são descritas como transcritas/estimadas.

## Linguagem visual

A janela PyQt5 é densa e orientada por estados: o botão de gravação e a região de
status precisam indicar claramente quando a captura está disponível, ativa ou encerrada.
As falas de usuário e Dogen usam cores distintas nos rótulos, mantendo o texto da conversa
neutro. Cada configuração tem um botão `?` com explicação curta.
Detalhes da evolução de aprendizagem estão no design datado vinculado em `architecture.md`.
