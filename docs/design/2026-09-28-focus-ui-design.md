# Dogen — foco na conversação e HUD estável

## Objetivo

Fazer a conversa falada ser a ação principal do Dogen. A interface não deve pedir
que a pessoa preencha exercícios durante o fluxo normal; correções e progresso devem
ser informação de apoio, não uma segunda atividade competindo com a conversa.

## Decisões de produto

- `Today` será um resumo passivo de prática: minutos ativos, palavras faladas,
  turnos concluídos, fillers por 100 palavras, correções encontradas e sequência.
- `Fixes` será somente leitura. O painel exibirá correção, frase natural e categoria,
  sem campo de resposta, Retry, Explain ou Skip.
- `Status` deixará de ser um painel independente. Carregamento, pronto, gravação e
  processamento serão estados da região de captura/volume.
- A barra de volume só mostrará atividade do microfone durante a gravação do usuário.
  A escala visual será ampliada sem alterar o limiar real do microfone.
- A voz feminina continuará sendo a única voz exposta no produto.

## Layout

```text
┌ File ────────────────────────────────────────────────────────────────┐
│                         face do Dogen                                │
├───────────────────────────────────────────────┬───────────────────────┤
│                                               │ Today                 │
│              conversa                         │ métricas passivas     │
│                                               ├───────────────────────┤
│                                               │ Fixes (somente leitura)│
├───────────────────────────────────────────────┴───────────────────────┤
│ mensagem de estado ou barra de volume                 [gravar/parar]  │
└───────────────────────────────────────────────────────────────────────┘
```

A janela abrirá maximizada, manterá tamanho mínimo estável e usará limites explícitos
para a coluna lateral. Textos longos não poderão alterar a largura da janela.

## Menu File e diálogos

O menu File será a única entrada para nova sessão, exportação, progresso, vocabulário,
configurações, cenário, modelo e saída. Os diálogos receberão o mesmo fundo do HUD e
um componente reutilizável da face do Dogen no cabeçalho. Controles que não executarem
uma ação real serão removidos ou conectados ao fluxo existente.

## Retenção do modelo

O pipeline continuará residente enquanto a janela estiver aberta. As chamadas ao Ollama
usarão retenção explícita durante a vida do processo, incluindo o aquecimento inicial,
para evitar que o modelo seja descarregado depois de inatividade. O pipeline não será
recriado entre turnos normais.

## Limites e segurança

- Não criar nota de pronúncia, fluência ou proficiência.
- Não enviar áudio ou histórico para a nuvem.
- Replay e parar áudio continuam sem criar novo turno.
- Áudio persistido continua exigindo opt-in explícito.

## Verificação

- Testes existentes do pipeline e da UI continuam passando.
- Teste manual confirma que Today não inicia ações, Fixes não possui entrada editável,
  e o botão de gravação alterna corretamente entre início e término.
- Teste manual de espera confirma que o segundo turno após inatividade não recarrega
  o modelo visivelmente.
- Screenshot da janela principal e de cada diálogo confirma fonte, cor, logo e layout
  estáveis em tamanho maximizado e em uma janela reduzida até o mínimo.
