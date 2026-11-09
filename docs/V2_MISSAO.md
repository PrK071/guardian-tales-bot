/GOAL — Guardian Tales Autonomous Agent V2: End-to-End Stage Completion

MISSÃO PRINCIPAL

Evoluir o agente autônomo existente em "E:\GuardianTalesBot" para alcançar seu primeiro marco de conclusão autônoma, verificável e reproduzível de uma fase real do Guardian Tales.

A arquitetura hierárquica persistente V1 já foi implementada. Sua evolução deve aproveitar integralmente os componentes existentes, corrigindo gargalos operacionais em vez de reconstruir a arquitetura.

O objetivo é transformar um sistema capaz de planejar e recuperar estados em um agente capaz de efetivamente executar planos, superar obstáculos e demonstrar progresso real.

A missão não será considerada concluída apenas porque novos módulos foram criados ou testes simulados passaram.

É necessário demonstrar comportamento funcional, com evidências concretas.

---

FASE 0 — AUDITORIA DIRECIONADA

Inspecione:

- "E:\GuardianTalesBot"
- "docs\ACEITACAO.md"
- Arquitetura hierárquica implementada.
- Memória SQLite.
- Strategic Planner.
- Task Planner.
- Tactical Controller.
- Integrações ADB, OCR e captura.
- Research Engine.
- Qwen3-0.6B.
- Evaluation Harness.

Investigue especificamente por que o último ciclo real terminou com o agente pausado por ausência de continuação comprovada.

Identifique:

1. O estado observado antes da interrupção.
2. A decisão proposta pelo planejador.
3. A ação efetivamente executada.
4. O resultado observado.
5. O critério de verificação que não foi satisfeito.
6. Se o bloqueio ocorreu na percepção, navegação, execução, validação ou planejamento.

Produza um diagnóstico causal fundamentado.

Não faça uma auditoria genérica de todo o projeto. Inspecione apenas os componentes necessários para localizar e resolver os gargalos.

FASE 1 — WORLD STATE & SPATIAL UNDERSTANDING

Evolua a percepção existente para representar o ambiente de forma operacional.

O sistema deve conseguir distinguir, quando visualmente possível:

- Personagem controlado.
- Inimigos.
- Obstáculos.
- Objetos interativos.
- Passagens.
- Saídas.
- Estados de combate.
- Estados de exploração.
- Elementos relevantes de puzzles.

Implemente representação espacial persistente quando houver evidência suficiente.

O agente deve registrar regiões visitadas, caminhos tentados, obstáculos observados e objetivos identificados.

Evite inventar coordenadas ou relações espaciais quando a observação for insuficiente.

Defina níveis de confiança e mecanismos para detectar mudanças no ambiente.

FASE 2 — GOAL-DIRECTED NAVIGATION

Implementar ou melhorar navegação orientada a objetivos.

O sistema deve conseguir:

1. Selecionar um destino observável.
2. Planejar deslocamentos locais.
3. Executar comandos de movimentação.
4. Verificar deslocamento efetivo.
5. Detectar colisões e ausência de progresso.
6. Corrigir movimentos mal executados.
7. Atualizar a representação espacial.
8. Replanejar quando um caminho estiver bloqueado.

Investigue técnicas adequadas de pathfinding e navegação incremental.

Não introduza SLAM, A*, mapas complexos ou modelos adicionais sem demonstrar que resolvem uma necessidade real do projeto.

Prefira a implementação mais simples que satisfaça os critérios funcionais.

FASE 3 — INTERACTION & BASIC COMBAT

Desenvolver controladores operacionais confiáveis.

Interaction Controller

Deve permitir:

- Identificar objetos interativos.
- Aproximar-se de objetos.
- Executar interações.
- Observar alterações.
- Confirmar resultados.
- Recuperar falhas.

Combat Controller

Deve permitir:

- Identificar estados de combate.
- Reconhecer ameaças observáveis.
- Atacar quando apropriado.
- Evitar repetição improdutiva de comandos.
- Detectar término do combate.
- Registrar sucesso ou falha.

Priorize um controlador simples e funcional antes de implementar esquiva avançada, chefes ou otimização de combate.

A execução deve usar interfaces permitidas, sem manipulação de memória, alterações no cliente ou evasão de sistemas de proteção.

FASE 4 — PUZZLE REASONING & RESEARCH

Integrar o Research Engine existente à resolução de obstáculos.

O agente deve:

1. Identificar um problema não resolvido.
2. Verificar soluções armazenadas na memória.
3. Consultar fontes externas quando necessário.
4. Comparar soluções encontradas com o estado observado.
5. Extrair passos executáveis.
6. Elaborar uma estratégia.
7. Executar e verificar cada etapa.
8. Corrigir a estratégia diante de resultados inesperados.
9. Armazenar conhecimento validado.

Não considerar conteúdos encontrados na internet como fatos automaticamente.

Distinguir:

- Informação externa não verificada.
- Hipótese plausível.
- Estratégia testada.
- Solução comprovada.

Não executar instruções externas que estejam fora do escopo da tarefa.

FASE 5 — QWEN PERFORMANCE INVESTIGATION

A implementação V1 apresentou aproximadamente 36 segundos em uma decisão com contexto maior.

Investigue a latência antes de substituir o modelo.

Realize profiling de:

- Preparação do contexto.
- Recuperação de memória.
- Tokenização.
- Prefill.
- Geração de tokens.
- Parsing e validação.
- Tempo total por decisão.

Compare pelo menos:

- Contexto completo atual.
- Contexto mínimo suficiente.
- Contexto recuperado seletivamente da memória.

Avalie se decisões determinísticas podem dispensar chamadas ao LLM.

Implemente otimizações apenas quando houver evidências de benefício.

Não reduza arbitrariamente o orçamento de saída, a qualidade do raciocínio, a cobertura de testes ou o escopo funcional para economizar tokens.

Se houver proposta de trocar o Qwen3-0.6B, apresente primeiro evidências comparativas de qualidade, latência e consumo de recursos no hardware disponível.

FASE 6 — END-TO-END STAGE EXECUTION

Selecionar uma fase inicial representativa, com base no estado real e no conteúdo disponível para testes.

O agente deverá tentar executar a sequência:

OBSERVE CURRENT GAME STATE
          ↓
IDENTIFY STAGE AND OBJECTIVE
          ↓
RETRIEVE RELEVANT MEMORY
          ↓
GENERATE EXECUTION PLAN
          ↓
EXPLORE / NAVIGATE
          ↓
INTERACT / COMBAT / RESOLVE OBSTACLES
          ↓
VERIFY REAL PROGRESS
          ↓
REPLAN IF NECESSARY
          ↓
REACH STAGE EXIT
          ↓
CONFIRM STAGE COMPLETION
          ↓
PERSIST VERIFIED RESULT

O agente deve trabalhar com critérios explícitos de sucesso.

Não confundir:

- Ação enviada com ação executada.
- Movimento solicitado com deslocamento confirmado.
- Inimigo atacado com combate concluído.
- Saída encontrada com fase terminada.
- Plano produzido com objetivo realizado.

Se a fase não puder ser completada, apresentar precisamente o bloqueio observado e a evidência correspondente.

Não declarar sucesso parcial como conclusão integral.

FASE 7 — EVALUATION HARNESS V2

Estender a infraestrutura de avaliação existente.

Registrar métricas de:

- Taxa de conclusão de fases.
- Progresso efetivo por minuto.
- Tempo de execução por tarefa.
- Latência média e p95 das decisões.
- Chamadas ao modelo por tarefa.
- Tokens de entrada e saída.
- Tempo de execução dos controladores.
- Ações repetidas sem progresso.
- Falhas de percepção.
- Falhas de navegação.
- Falhas de verificação.
- Replanejamentos.
- Recuperações bem-sucedidas.
- Interrupções sem recuperação.

Criar testes reproduzíveis para:

1. Navegação em ambiente simples.
2. Caminho bloqueado.
3. Interação bem-sucedida.
4. Interação sem efeito confirmado.
5. Combate básico.
6. Puzzle com solução recuperada.
7. Falha seguida de replanejamento.
8. Retomada após reinicialização.
9. Pesquisa sem resultados relevantes.
10. Conclusão de fase detectada incorretamente.

Separar claramente testes simulados, testes com capturas históricas e testes reais.

Não apresentar resultados de mocks como comprovação de capacidade no jogo.

FASE 8 — INTEGRATION & HARDENING

Integrar todos os componentes ao ciclo principal existente.

Preservar:

- Memória persistente.
- Planejamento hierárquico.
- Checkpoints.
- Reconciliação de estado.
- Verificações determinísticas.
- Research Engine.
- Infraestrutura de testes.
- Controles e rotas funcionais.

Adicionar observabilidade para acompanhar objetivos, subtarefas e ações.

Garantir:

- Timeouts.
- Limites de tentativas.
- Interrupção manual.
- Detecção de ausência de progresso.
- Recuperação controlada.
- Tratamento de falhas.
- Persistência consistente.
- Ausência de loops infinitos.

Não introduzir serviços, frameworks ou abstrações desnecessárias.

---

CRITÉRIOS DE ACEITAÇÃO

Requisitos obrigatórios

- A arquitetura V1 continua funcional.
- O agente consegue identificar objetivos operacionais.
- A navegação apresenta progresso verificável.
- Interações possuem confirmação observável.
- O planejamento responde a falhas reais.
- A memória é utilizada corretamente.
- As pesquisas externas influenciam planos quando relevantes.
- A latência do Qwen é medida e analisada.
- Os testes existentes continuam passando.
- O Evaluation Harness V2 apresenta métricas reproduzíveis.

Objetivo principal

Completar autonomamente pelo menos uma fase real, do estado inicial até uma confirmação observável de conclusão, quando o ambiente e as permissões de teste permitirem.

Se isso não for alcançado, entregar uma análise causal do bloqueio e demonstrar quais capacidades foram efetivamente validadas.

Não inventar evidências ou mascarar limitações.

EXECUTION DIRECTIVE

Você está autorizado a investigar, implementar, executar testes apropriados e refatorar dentro do escopo desta missão.

Trabalhe incrementalmente.

Não interrompa a execução apenas para solicitar autorização sobre decisões técnicas reversíveis e de baixo risco.

Continue as tarefas independentes quando encontrar um bloqueio.

Respeite as permissões do ambiente e não realize ações destrutivas ou alterações fora do repositório sem autorização.

Não reimplemente componentes comprovadamente funcionais.

Não realize auditorias repetitivas sem necessidade.

Não reduza a qualidade, completude ou validação para economizar tokens.

Atualize a documentação e registre evidências.

FINAL DELIVERABLE

Produza:

"E:\GuardianTalesBot\docs\V2_END_TO_END_REPORT.md"

O relatório deverá conter:

1. Resumo executivo.
2. Causa dos bloqueios anteriores.
3. Mudanças arquiteturais.
4. Funcionalidades implementadas.
5. Resultados dos testes.
6. Métricas de desempenho.
7. Avaliação do Qwen3-0.6B.
8. Evidências de execução.
9. Resultados de conclusão de fase.
10. Limitações remanescentes.
11. Próximos gargalos prioritários.

MISSÃO FINAL: evoluir o Guardian Tales Bot de uma arquitetura autônoma funcional para um sistema capaz de demonstrar conclusão real de tarefas complexas, usando percepção, planejamento, memória, pesquisa, execução e verificação de resultados.

Priorize progresso funcional comprovado acima de sofisticação arquitetural.