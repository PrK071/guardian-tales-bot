# Auditoria de aceitação da base autônoma

Escopo: a missão em `MISSAO.md` pede a base de um agente hierárquico persistente. Não se confunde com comprovar que todos os mundos do jogo estão automatizados. As evidências abaixo distinguem execução real, replay de imagens e simulação.

## Critérios

| Requisito | Evidência inspecionada | Resultado e limite |
|---|---|---|
| Auditoria antes de implementar e plano incremental | `AUDITORIA-ARQUITETURAL.md`, backup dos quatro arquivos anteriores e execução inicial dos 12 testes | Realizada; núcleo existente reutilizado |
| Arquitetura hierárquica integrada | `cognitive/planning.py`, `runtime.py`, jobs em `bot.py`, `evaluations/live-cycle.json`, `live-model-cycle.json` | Estratégia → tarefa → controle → observação/verificação funcionando no processo existente |
| Decomposição verificável | Testes `task_has_verifiable_contract_and_dependencies`, `decomposition_executes_and_requires_two_result_observations` | Tarefas com pré-condições, sucesso, dependências, orçamento, recuperação, estado e evidências |
| Memória persistente após reinicialização | `live-resume.json`, testes de reopen, backup, escopo e crash | Objetivo e IDs de tarefas preservados em reinício real; integridade SQLite OK |
| Experiência influencia decisões futuras | `previous_failure_influences_next_session`, `verified_strategy_is_retrieved_by_future_planner`, `live-resume.json` | No teste simulado uma falha impede repetir a rota; no jogo real a pesquisa anterior foi reutilizada sem nova consulta |
| Pesquisa externa integrada | `live-research.json`, `live-cycle.json`, registros `research` em `logs/cognitive.jsonl` | Busca e extração HTTP reais, três requisições na avaliação, cache na segunda consulta; fontes permanecem reported |
| Detecção de falhas e replanejamento | Cenário `wall_no_progress`, testes de falha de percepção, combate, ciclos e critérios sem efeito | Abandona tentativa sem efeito, registra classe de falha, investiga ou bloqueia |
| Checkpoints restaurados com reconciliação | Testes `uncertain_command_not_repeated...`, `uncertain_effect_can_be_confirmed...`, `interrupted_subtask_resumes...`; `live-resume.json` | Estado visual fresco prevalece; efeito incerto não é repetido; destino comprovado permite concluir sem reenviar |
| Recuperação após encerramento inesperado | `process_crash_preserves_journal` usa subprocesso real com `os._exit(19)` após issued/checkpoint | Banco recuperado mantém operação incerta; nenhuma ação do jogo é enviada por esse teste |
| Avaliação reproduzível | `run_tests.py`, `harness.py`, `scenarios.json`, `perception_corpus.py`, relatórios JSON | 45 testes atuais passam; 4 cenários × 2 variantes; 3 capturas reais em replay |
| Contratos, argumentos, timeouts e concorrência | Testes de ações inválidas, dependências cíclicas, lease, parada, ausência de confiança e destinos de pesquisa | Entradas e efeitos delimitados; um executor cognitivo por lease; não há controle simultâneo na fila |
| Integridade e logs | `memory.py`, testes de banco corrompido e backup; trilha JSONL com tarefa/operação/observações | Corrupção não é apagada ou mascarada; operações têm journal transacional |
| LLM de alto nível sem chamada por movimento | `real-model.json`, `live-model-cycle.json`, `model-cancel.json`, `local_model.py` | Inferência textual real Qwen3-0.6B/llama.cpp integrada; controles táticos não dependem de inferência por comando |
| Documentação de decisões/limites | `ARQUITETURA-COGNITIVA.md`, este arquivo e `LEIA-ME.md` | Componentes, memória, pesquisa, recuperação, uso e marcos documentados |
| Funcionalidade anterior preservada | Os 12 testes legados estão entre os 45; corpus usa o OCR/CV legado; painel desktop/mobile passa | Nenhuma regressão conhecida nesses controles; isso não prova todos os estados possíveis do jogo |

## Evidência real no jogo

Primeiro ciclo hierárquico: a fase foi identificada como `world:1:passage:1`; o agente retomou a interface por um botão OCR observado, confirmou `jogo`, pesquisou a continuação e bloqueou a execução sem inventar uma rota. Foram três ciclos, uma ação e uma investigação. O processo foi reiniciado e a próxima execução preservou o objetivo e as tarefas, reutilizando o conhecimento sem outra investigação.

Depois da integração de modelo: um ciclo real consultou Qwen3-0.6B com 1.238 tokens de entrada e 72 avaliações de tokens de saída reportadas pelo llama.cpp; a inferência levou aproximadamente 29 s com o contexto maior. O ciclo verificou uma retomada de UI. Isso é evidência de integração e verificação, não de concluir a fase ou solucionar puzzles.

O primeiro teste de modelo sugeriu uma rota inexistente. O relatório da falha foi preservado. Após restringir a saída às possibilidades sustentadas pelo contexto, o modelo escolheu inspeção no mesmo caso. O modelo é pequeno e continua falível; as guardas e os checkpoints permanecem necessários.

A execução final da implementação atual está em `evaluations/final-live-cycle.json`: dois ciclos, uma consulta ao modelo e duas ações de UI verificadas (retomar e pausar). Sem continuação executável comprovada, o agente encerrou o orçamento de trabalho em bloqueio explícito, deixando o próprio jogo pausado. Foram reportados 1.415 tokens de entrada e 67 avaliações de saída, com aproximadamente 36 s de inferência no contexto maior. A captura final está em `evaluations/final-game-paused.jpg`. A fase continua não concluída.

## Benchmark e interpretação

Consulte `evaluations/benchmark.json` para os tempos efetivamente medidos na execução mais recente. Os cenários são determinísticos e condicionados às ações; não enviam comandos ao jogo. A baseline A é uma política monolítica reativa explicitamente simples, sem memória. B usa a implementação hierárquica e SQLite, com pesquisa sintética identificada como fixture. Ambas recebem os mesmos cenários e limites.

No cenário da parede, A tentou mover dez vezes, enquanto B tentou uma vez e passou à investigação/bloqueio. No cenário de progressão, ambas alcançaram o resultado simulado; B também exigiu confirmação de conclusão. A hierarquia acrescenta custo de persistência/verificação: não há alegação de ser mais rápida. O benchmark sem modelo consome zero tokens; não deve ser confundido com a inferência local medida separadamente. Não há evidência estatística de taxa de vitória em fases reais.

O corpus de três screenshots acertou as três cenas/identidades esperadas. A amostra não permite concluir precisão geral. O protocolo HTTP de modelo foi testado com resposta simulada; a inferência real é comprovada separadamente pelos pesos locais e respectivos relatórios.

## Limites e marcos pendentes

- História inteira, fases completas adicionais, esquiva de armadilhas e chefes não estão validados.
- O modelo instalado é textual; não há VLM ou análise de vídeo. Modelos maiores exigem avaliação própria.
- As fontes externas fornecem hipóteses e referências. Não existe extração universal de soluções executáveis de puzzles.
- O minimapa e a detecção de inimigos/vida são aproximações; a percepção de objetos, bloqueios e pré-requisitos precisa ser ampliada por casos.
- Uma consulta em idioma não compreendido pelas regras pode servir apenas como referência. A utilidade de uma estratégia é promovida somente após verificação no jogo.
- Avaliação de custo local não inclui eletricidade/hardware. O adaptador HTTP opcional depende das informações de uso do provedor.

Essas pendências são marcos de capacidade do jogo. A aceitação desta base arquitetural não as transforma em funcionalidades concluídas.
