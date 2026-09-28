# Task 5 — verificação final e aceite disponível

## Comandos e resultados

- `PYTHONPATH=. pytest -q`: primeira execução, 109 passaram e 1 falhou. O teste `test_ollama_client_sets_context_window` usava um cliente falso sem o argumento `keep_alive`, introduzido na implementação aprovada do Task 4.
- Atualizado somente esse teste para aceitar e conferir `keep_alive=-1`, além da janela de contexto de 4096 tokens. Nenhum código de produto foi alterado.
- `PYTHONPATH=. pytest -q`: 110 passaram na execução final, em 11,45 segundos.
- `git diff --check`: saída 0; apenas aviso de conversão LF para CRLF em `tests/test_core.py`, sem erro de whitespace.

## Aceite manual

- O Windows identificou um microfone de entrada (`Microfone (High Definition Audi`, índice 1).
- Dogen iniciou como processo e o Windows mostrou uma janela com título `Dogen`. A ferramenta de inspeção de janelas da sessão não listou essa janela como alvo, portanto não foi possível observá-la ou interagir com ela. O processo aberto para o teste foi encerrado.
- Permanecem sem verificação visual: abertura maximizada, redimensionamento ao mínimo, HUD inferior de carregamento, ausência de botões em Today, Fixes sem campo editável, ações do menu File, fundo e logo dos diálogos, barra limitada ao estado de gravação, replay e stop.
- Nenhum turno falado foi executado. A retenção visível do Ollama após alguns minutos e um segundo turno permanecem sem aceite manual. Não há screenshot, vídeo, medida de recarga ou evidência de proficiência, fluência ou pronúncia deste checkpoint.

## Resultado

Verificação automatizada concluída; aceite humano da interface e do fluxo de áudio continua pendente. O estado foi registrado em `docs/quality/daily-practice-release-report.md` sem converter os testes automatizados em evidência manual.
