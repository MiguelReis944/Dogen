# Regras do projeto

## Invariantes

- O produto é offline-first; credenciais e modelos ficam na máquina do usuário.
- Correção gramatical, sugestão de frase e confiança de reconhecimento são conceitos
  diferentes e não devem ser misturados.
- Replay e stop não chamam o Ollama nem criam um turno novo.
- Não exibir nota de pronúncia, fluência ou proficiência sem avaliador validado.

## Restrições

Áudio persistido exige opt-in explícito e deleção imediata. A voz e os modelos padrão
devem continuar configuráveis sem introduzir uma dependência de nuvem.

## Regras de trabalho

Consulte `README.md`, `docs/quality/` e os designs datados antes de mudar o pipeline.
Não transformar uma proposta de learning system em requisito implementado sem evidência
no código ou aprovação da pessoa responsável.
