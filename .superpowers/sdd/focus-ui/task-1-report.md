# Task 1 — HUD de captura

## Arquivos alterados

- `ui/main_window.py`
- `ui/styles.qss`
- `tests/test_window.py`

## Testes executados

- Antes da mudança: `pytest tests/test_window.py -q` não coletou os testes porque o ambiente não incluiu a raiz do projeto no `PYTHONPATH` (`ModuleNotFoundError: nlp`).
- Depois da mudança: `PYTHONPATH=. pytest tests/test_window.py -q` — 26 passaram.
- `git diff --check` — sem erros de whitespace.

## Decisões

- O estado e o medidor agora ficam numa faixa inferior dedicada, e o grupo lateral `Status` foi removido.
- O medidor só é selecionado e atualizado durante `recording`; fora desse estado, volta a zero e a mensagem fica visível.
- A janela tem mínimo de 1100 × 700; a lateral fica entre 320 e 420 px, e a conversa mantém largura mínima de 500 px.
- O rótulo de estado tem largura ignorada pelo layout e altura limitada para mensagens longas não redimensionarem a janela.
- Os fluxos dos botões `Start recording` e `Finish recording` e o pipeline não foram alterados.

## Preocupações

- A execução literal do comando de baseline depende de `PYTHONPATH=.` neste ambiente. Com esse ajuste, a suíte direcionada passa integralmente.
- A janela maximizada e o layout em tamanho mínimo não foram inspecionados manualmente por screenshot.
