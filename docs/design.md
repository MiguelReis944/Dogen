# Design de interação

## Jornadas de uso

Na abertura, Dogen carrega dependências e explica o estágio atual. A pessoa clica em
Start recording, fala, clica em Finish recording, acompanha a resposta e pode revisar
a transcrição antes do envio. Depois pode ouvir novamente ou parar o áudio.

## Interação e comportamento

O painel principal mostra conversa; `Fixes` separa correções e frases alternativas;
`Status` mostra carregamento e estágio. `File` concentra cenário, modelo e progresso;
`Settings` contém revisão de transcrição, opções de captura e a meta de gravação diária
exibida em Today (15 minutos por padrão). Today mostra o tempo de áudio capturado numa
única linha; contagens de palavras e fillers são descritas como transcritas/estimadas.

## Linguagem visual

A janela PyQt5 é densa e orientada por estados: o botão de gravação e a região de
status precisam indicar claramente quando a captura está disponível, ativa ou encerrada.
Detalhes da evolução de aprendizagem estão no design datado vinculado em `architecture.md`.
