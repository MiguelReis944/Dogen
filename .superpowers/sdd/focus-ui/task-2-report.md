# Task 2 — Today e Fixes passivos

## Arquivos

- `ui/main_window.py`: adiciona o resumo Today como conteúdo de leitura e atualiza os dados após abrir a janela e concluir um turno.
- `tests/test_window.py`: cobre as métricas, a ausência de botões no Today, a leitura exclusiva do Fixes e a preservação de correção, frase natural e categoria.
- `.superpowers/sdd/focus-ui/task-2-report.md`: este relatório.

`ui/styles.qss` não precisou de mudanças; o painel usa o estilo já aplicado à janela.

## Testes

- Antes: `PYTHONPATH=. pytest tests/test_window.py tests/test_progress.py -q` — 33 passaram.
- TDD: o novo teste de Today falhou porque `MainWindow` ainda não expunha `today`; o teste de Fixes passou porque o painel já era somente leitura.
- Depois: `PYTHONPATH=. pytest tests/test_window.py tests/test_progress.py -q` — 35 passaram.
- `git diff --check` — sem erros de whitespace.

## Decisões

- Today mostra minutos ativos, palavras faladas, turnos concluídos, fillers por 100 palavras, correções e sequência, filtrados para a data local atual.
- Quando ainda não há palavras métricas, fillers por 100 palavras aparece como “Not enough data”.
- Fixes permanece `QTextEdit` somente leitura; sua renderização de correção, frase natural e categoria e a persistência do turno continuam cobertas.
- Mantive o Retry de revisão da transcrição, que permite corrigir ou descartar a transcrição antes de enviá-la à conversa. Ele não é uma ação de exercício em Fixes. O estado inicial já não tinha `correction_input`, Explain, Skip nem controles de Retry no Fixes.

## Preocupações

- Não existe uma API de progresso de um único dia no escopo permitido. Today consulta as tabelas SQLite locais já existentes e usa `ProgressService` para a sequência. A persistência e o esquema não foram alterados; uma API pública de agregados diários pode reduzir o acoplamento da UI ao banco em uma tarefa futura.
- A validação visual manual e screenshots descritos no design não foram executados nesta tarefa.
