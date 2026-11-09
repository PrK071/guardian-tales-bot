# Guardian Tales Autonomous Agent V2 — evidências e execução

Atualizado em 2026-11-08T04:34:07. Base: relatórios encerrados; execuções abertas não entram nas taxas.

## 1. Resumo executivo

**O marco principal permanece pendente: nenhuma fase real foi concluída do nascimento à confirmação de resultado.** Alvo observado: Mundo 1, 1-1 Floresta Kanterbury Passagem 1, Normal; objetivo de entrada: “Derrote monstros.” O agente demonstrou navegação e combate local, mas parou diante do puzzle de lanternas. O desenvolvimento continua incrementalmente em `E:\GuardianTalesBot`, preservando V1 em `backups/before-v2/`.

Foram encerradas 6 tentativas V2, sendo 3 iniciadas no nascimento e 3 retomadas. A taxa de conclusão desde o início é 0/3. Calibrações, preparação de menus e testes simulados são contabilizados separadamente.

## 2. Causa dos bloqueios anteriores

O último ciclo V1 (`evaluations/final-live-cycle.json`, `logs/cognitive.jsonl`) observou a Passagem 1 pausada, retomou a interface e depois decidiu `blocked`: não havia continuação executável comprovada para a rota parcial. As transições foram verificadas, mas não houve deslocamento do personagem. O gargalo era a ausência de navegação operacional entre checkpoints, com OCR repetido tornando a espera junto a ameaças lenta.

As tentativas V2 expuseram causas específicas, corrigidas com evidência dirigida:

- Fronteira sob o marcador gerava caminho zero: ignorar destinos sem deslocamento e reconstruir somente a oclusão entre pisos observados.
- Retrato do HUD confundido com inimigo e conflito de `kind` no registro: excluir retratos e aninhar os dados do evento.
- O mapa mudava escala/centro após explorar: alinhar silhueta do nascimento e comparar posições no mesmo referencial. Movimento real estava sendo rejeitado pela comparação bruta.
- Fundo verde escuro contado como vida cheia: contar apenas preenchimento brilhante. Captura de 54% passou a refletir a perda de vida.
- Efeito de ataque ocultava o capacete: reobservar até quatro vezes sem comandos, interrompendo se não recuperar.
- A barreira inferior permaneceu imóvel após comandos e correções laterais: pesquisa posterior identificou o puzzle de lanternas. Insistência em caminhar ao sul não o resolve.
- Captura Android inteira cinza entre imagens válidas: até três novas capturas sem entrada, preservando o buffer inválido.
- Nas calibrações posteriores, o desvio alternava subir/descer na trajetória de uma coluna de espinhos. Duas tentativas pararam com vida baixa. Foi implementada seleção de ponto de parada entre colunas observadas, com limite pelo trecho reto do mapa; essa estratégia ainda exige validação real. Movimento agora é retido se vida/ator falharem na captura imediatamente anterior à entrada.

O MSI também travou numa sessão anterior. Reconexão e reinício do servidor ADB não bastaram; o usuário reabriu o emulador. Novas observações e comandos reais confirmaram a recuperação. Uma desconexão TCP posterior foi recuperada com `adb connect`.

## 3. Mudanças arquiteturais

A arquitetura existente continua responsável pelo worker, ADB, memória SQLite, metas, tarefas, journal e checkpoints. V2 acrescenta controladores determinísticos à mesma fila; não cria um segundo executor concorrente.

`spatial.py` representa ator, barras de inimigos, ameaças e candidatos de objetos; `map_navigation.py` usa BFS no piso observado com margem de parede; `map_anchor.py` alinha escala/translação da silhueta inicial. `fast_control.py` registra imagens antes/depois, operações, deslocamento e lease. `stage_v2.py` integra execução, memória, reconciliação, pesquisa, métricas e duas observações do resultado. Os frames existentes alimentam o painel sem uma captura ADB adicional.

Uma entrada nova exige ticket de preparação fresco, não consumido, e posição coincidente com o nascimento conhecido. Um marcador num outro extremo inferior não recebe classificação de nascimento. Fronteiras bloqueadas podem ser adiadas temporariamente e reconsideradas após combate ou nova entrada observada. As fontes relevantes e seus hashes são copiadas para a pasta de cada execução.

## 4. Funcionalidades implementadas

- Exploração por fronteiras observadas, pulsos curtos, verificação por imagem/mapa, correção lateral limitada e replanejamento para outro destino observado.
- Combate básico contra barras atuais: aproximação, ataque e três observações de ausência após inimigo presente. Há checagem imediatamente antes do comando; perder o inimigo impede entrada cega.
- Conversa contextual por aparência do botão e mudança na região de diálogo, com até seis avanços. Existência do controlador não comprova interação real onde não há registro.
- Hipótese de bomba/pedra compilada de fonte textual; pegar, lançar e remover precisam de evidência visual. Não é declarada solução da barreira das lanternas.
- Visão de braseiro portátil e lanternas com templates desta conta e proveniência; chamas da barreira laranja não contam como lanternas acesas.
- Memória de pontos de observação de objetos, vinculando imagem do objeto à posição real do ator no mapa anterior ao movimento. Retornar ao ponto exige reencontrar o objeto em imagem nova.
- Calibração de coleta do braseiro com botão contextual, desaparecimento no chão, aparência sobre o ator e teste de acompanhamento após movimento. A existência desse código não comprova coleta até os testes reais confirmarem.
- Calibração segura do joystick: toque fixo superior por 900ms deslocou 53,19 pixels de referência, aproximadamente o dobro do swipe anterior. V2 usa toque fixo, com duração limitada ao trecho reto; V1 preserva seu comando original. `v2_joystick_calibration_eb3322a2ece34a78/report.json` preserva medição e incerteza da comparação imediata de câmera.
- A aproximação da fonte de fogo e reconciliação do objeto carregado estão implementadas como experimentos limitados. Não foram promovidas a solução comprovada de puzzle.

## 5. Resultados dos testes

V1: consultar `evaluations/unit-report.json`, última regressão conhecida 45/45. V2 consolidado: **59/59**. Grupos históricos são imagens reais reprocessadas; grupos simulados não executam comandos na conta.

| Grupo | Passaram/total |
| --- | --- |
| simulated | 10/10 |
| simulated_stage_integration | 4/4 |
| simulated_puzzle_controller | 7/7 |
| simulated_map_alignment | 4/4 |
| simulated_combat_guard | 5/5 |
| simulated_recovery_and_initial_state | 4/4 |
| simulated_lantern_guards | 5/5 |
| simulated_hazard_endpoints | 6/6 |
| historical_real_screenshots | 11/11 |
| historical_lantern_vision | 3/3 |

Os dez cenários obrigatórios cobrem navegação, bloqueio, interação com/sem efeito, combate, hipótese recuperada, replanejamento, retomada, pesquisa sem resultado e falso positivo de conclusão. SQLite temporário dos testes não recebe status de conclusão na memória da conta.

Reproduzir: Python do projeto com `evaluations/run_tests.py`, `evaluations/v2/test_scenarios.py` e, para métricas/documentação, `evaluations/v2/summarize.py` seguido de `evaluations/v2/write_report.py`. Não é necessário repetir o profiling do modelo para essas verificações.

## 6. Métricas de desempenho

Tentativas encerradas: 752.623 s, 289 ações. Ciclo completo: média 7733.989 ms, p95 8766.925 ms. Planejamento local isolado, nas versões que o separaram: média 310.436 ms, p95 556.207 ms. Não misturar o antigo `decision_ms`, que media o ciclo inteiro, com a latência isolada.

Controlador: média 1300.446 ms, p95 2049.24 ms. Foram confirmados 59 movimentos com extensão estável e 34 com alinhamento; os conjuntos podem sobrepor-se. Progresso alinhado: 40.697 pixels de referência/minuto; não é distância física nem percentual da fase.

Contadores registrados: 4 falhas de navegação, 5 recuperações e 6 interrupções sem recuperação na respectiva tentativa. Alguns erros antigos não foram classificados por esses contadores: os motivos textuais de cada relatório são a evidência causal. 0 chamadas ao modelo, 0 tokens de entrada e 0 de saída no loop determinístico. P95 usa nearest rank.

As nove calibrações anteriores somam 294.389 s, 118 ações e 40 movimentos, com 14 confirmações de mapa estável. As calibrações de lanternas abaixo são separadas.

## 7. Avaliação do Qwen3-0.6B

Mesmo Qwen3-0.6B Q8, duas threads, orçamento de saída de 160 tokens, nove inferências reais. Pesos e configurações preservados; modelo não substituído.

| Contexto | Tokens de entrada | Média (s) | P95 (s) | Respostas fundamentadas |
| --- | --- | --- | --- | --- |
| full_current | 1433 | 37.865 | 39.615 | 3/3 |
| minimal | 302 | 10.678 | 10.706 | 3/3 |
| selective | 670 | 20.497 | 21.924 | 3/3 |

Recuperação de memória na ordem de 2 ms; o tamanho de entrada domina o prefill. O perfil mede preparação, recuperação, tokenização/probe, inferência, geração e parsing; o probe inclui inicialização do processo. Detalhes brutos: `evaluations/v2/qwen-profile.json`. Três amostras por contexto num caso de UI não são benchmark de puzzles. O contexto seletivo permanece opcional; decisões locais dispensam LLM quando há critério visual determinístico.

## 8. Evidências de execução

Cada pasta `data/v2/v2_trial_*/` preserva relatório, eventos, navegação, capturas e hashes. Evidências centrais:

- `v2_trial_5aa90fc7327340cf`: 42 ciclos desde o nascimento, passagem pelo encontro e armadilhas; parou na mudança de escala do mapa.
- `v2_trial_7f2943bf285b4f4b`: alinhamento validado na navegação real; interrompida para corrigir leitura de saúde.
- `v2_trial_604785b78ceb4a41`: inimigo e efeito que oculta o capacete; origem da reobservação sem comandos.
- `v2_trial_99d348c7cb44486e`: ataques reais e três ausências de barras; depois barreira imóvel. `0315-before-move.jpg` mostra lanternas inferiores apagadas; `0225-before-move.jpg` mostra braseiro central.
- `evaluations/v2/object-vantage-replay.json`: objetos visíveis associados a posições observadas; replay não prova novas ações.
- `data/v2/v2_preparation_6368d8e306544534/report.json`: nova entrada real, objetivo OCR e nascimento pausado, sem comandos de personagem.

Pesquisa: [wiki da Passagem 1](https://guardian-tales.fandom.com/wiki/Kanterbury_Forest_Passage_1) e [vídeo observado](https://www.youtube.com/watch?v=P8Kob7UhlNs&t=89s). Quadros 1:29, 1:32, 1:36 e 1:41 mostram braseiro, transporte, chama e combate após a barreira. A sequência é hipótese para esta conta. `knowledge/v2_lantern_research.json` registra fontes, tempos e limites; nenhuma fonte externa é código executável.

Calibrações encerradas das lanternas:

- `data\v2\v2_lantern_calibration_52b8b4ecd2df48c9\report.json`: fase `approach`, 1.985 s, 0 ações; resultado `null`; erro `RuntimeError: Cannot transition from unrecognized screen: unknown; pause: Cannot transition from unrecognized screen: unknown`.
- `data\v2\v2_lantern_calibration_57d3f511303f48c8\report.json`: fase `approach`, 0.28 s, 0 ações; resultado `null`; erro `RuntimeError: error: device '127.0.0.1:5555' not found; pause: error: device '127.0.0.1:5555' not found`.
- `data\v2\v2_lantern_calibration_64f19690f25f4c65\report.json`: fase `arrive`, 376.387 s, 135 ações; resultado `null`; erro `InterruptedError: V2 manually stopped`.
- `data\v2\v2_lantern_calibration_8617713a0ec24422\report.json`: fase `arrive`, 134.035 s, 41 ações; resultado `null`; erro `RuntimeError: Low player health; navigation interrupted for recovery`.
- `data\v2\v2_lantern_calibration_bcd0a8a339db4292\report.json`: fase `arrive`, 60.766 s, 22 ações; resultado `null`; erro `RuntimeError: Cannot transition from unrecognized screen: unknown`.
- `data\v2\v2_lantern_calibration_cface23508d84a6d\report.json`: fase `arrive`, 199.057 s, 65 ações; resultado `null`; erro `RuntimeError: Low player health; navigation interrupted for recovery`.

## 9. Resultados de conclusão de fase

**0 conclusões comprovadas desde o início.** Nenhuma rota completa reproduzível. O critério exige duas observações independentes de resultado reconhecido, fase correta e ausência de tela bloqueada; chegar a uma fronteira ou eliminar inimigos visíveis não basta.

| Execução | Tipo | Resultado | Segundos | Motivo |
| --- | --- | --- | --- | --- |
| v2_trial_5aa90fc7327340cf | initial_stage_trial | blocked | 319.069 | Four unverified movements including recovery; local route needs obstacle evidence |
| v2_trial_604785b78ceb4a41 | resumed_stage_trial | blocked | 56.259 | Controlled character not confidently located |
| v2_trial_76dca5350b004dbb | initial_stage_trial | blocked | 4.083 | Already at the observed destination; need a new objective |
| v2_trial_7f2943bf285b4f4b | resumed_stage_trial | interrupted | 110.839 | — |
| v2_trial_99d348c7cb44486e | resumed_stage_trial | blocked | 253.529 | Observed edge blocked; bounded side-step recovery unavailable |
| v2_trial_dfcf9912d4a94e9e | initial_stage_trial | blocked | 8.844 | TypeError: CognitiveRuntime.event() got multiple values for argument 'kind' |

## 10. Limitações remanescentes

Cobertura restrita à Passagem 1, conta/costume atual e 1600×900. Não há bot comprovado para toda a história. Armadilhas causaram dano; recuperação de saúde não está automatizada. Inimigos fora da tela não são considerados eliminados; ajuda da NPC impede atribuir toda eliminação ao bot.

Coleta, fogo transportado, lanternas e abertura da barreira ainda exigem validação atual. Detector de saída não está calibrado. O controlador de bomba continua experimental; o puzzle atual é de lanternas. Templates reconhecem aparências, sem compreensão geral de mapas ou objetos.

Há limites de tentativas, tempo, saúde, falta de movimento e percepção; o evento de parada/painel e `data/v2/STOP` interrompem o loop. A pausa é tentada no encerramento; perder ADB impede garanti-la. Operações incertas não recebem replay cego. Limite externo pode ser ultrapassado por uma ação ou pesquisa em andamento com timeout próprio.

## 11. Próximos gargalos prioritários

1. Validar a coleta real do braseiro e fogo acompanhando o ator longe da fonte.
2. Verificar cada lanterna fixa após afastamento e a travessia da antiga barreira.
3. Resolver o último combate e observar a saída/resultado real.
4. Integrar a sequência validada e executar desde nova entrada até duas confirmações de resultado; repetir numa segunda tentativa.
5. Somente após essa evidência ampliar a cobertura para outras fases.
