# Auditoria anterior à implementação cognitiva — 2026-11-07

## Evidência inspecionada

Fonte: `bot.py`, `test_bot.py`, `config.json`, `routes/`, `knowledge/`, `LEIA-ME.md`, processo HTTP local e dispositivo ADB. Os 12 testes legados passaram novamente antes das alterações. O processo está vivo; a observação real identifica `pausa`, na Passagem 1 do Mundo 1. Não foi reiniciado por suposição de que estivesse parado.

## Arquitetura encontrada

`HTTP/panel → fila em memória → Bot.worker → observe/execute/route/combat → ADB`.

| Responsabilidade | Componente existente | Limite encontrado |
|---|---|---|
| Captura | `ADB.capture`, screencap Android | Sem contrato tipado ou persistência de observações |
| Percepção | `Bot.observe`, RapidOCR, HUD e barras por OpenCV | Regras de cena acopladas à execução; identidade de fase não persistida |
| LLM/VLM | Inexistente | Nenhum modelo/credencial configurado ou demonstrado |
| Decisão | Seleção manual de comandos e reprodução de JSON | Sem objetivos, dependências, reflexão ou planejamento estratégico |
| Controle | ADB tap/hold/move, controles normalizados | Reutilizável; precisa validar todos os argumentos e reconciliar resultados |
| Navegação | Rotas com fotografias e tolerância visual | Uma rota parcial; sem navegação geral ou solução de armadilhas |
| Combate | Barras vermelhas, aproximação e ataque | Experimental; não avalia objetivo concluído, esquiva ou chefe |
| Pesquisa | JSON com referências e links de busca | Nenhum subsistema de investigação executável |
| Memória | Deque, variáveis e logs; JSON de rotas | Estado do worker se perde ao encerrar; sem recuperação contextual |
| Avaliação | 12 testes de guardas; Playwright no painel | Sem cenários sequenciais, comparativo ou medição de decisões |

O manifesto de validação anterior é um registro declarativo; não é tratado como prova suficiente de capacidade. Os arquivos de calibração e o comportamento corrente corroboram apenas o trecho limitado. Não há evidência de fase completa ou história concluída.

## Reutilização e riscos

Preservar ADB, OCR, painel, fila única, guardas, rotas e testes legados. Acrescentar pacote `cognitive` no mesmo processo. Não introduzir múltiplos agentes, daemon extra, serviços de nuvem ou migração de framework: seria desnecessário para esta base Python existente.

Riscos: OCR pode confundir texto/identidade; salas parecidas podem coincidir; movimento executado não prova progresso; colisões/armadilhas exigem tática específica; operações podem ter efeito antes de uma queda; fonte externa não é autoridade operacional; ausência de LLM real limita compreensão aberta. Cada risco terá estado explícito, limites, evidências e interrupção/replanejamento, sem inventar validação.

## Plano incremental

1. Contratos de observação, ação, tarefa, evidência e resultado; banco SQLite com integridade, transações, versionamento e backup.
2. Adaptador do controlador existente, extração de contexto, três níveis de planejamento e ciclo verificar/refletir.
3. Recuperação de tarefas interrompidas sem repetir automaticamente efeitos; comparação do estado salvo com observação fresca.
4. Pesquisa HTTP real com cache, limites, procedência e status não verificado; integração estratégica por gatilhos.
5. Integração na fila/painel existente, parada manual e execução delimitada.
6. Cenários de avaliação reproduzíveis, regressões, reinicialização, falhas e demonstração integrada. Separar jogo real de replay/simulação.
7. Auditoria dos critérios de aceitação com ligações para evidências efetivamente produzidas.

## Disponibilidade verificada

Python portátil, OpenCV, NumPy, RapidOCR e SQLite estão disponíveis. ADB e o jogo estão conectados. HTTP de Bing RSS, DuckDuckGo HTML e o artigo GameChosun responderam à sondagem. Isso demonstra conectividade, não relevância garantida de toda pesquisa futura. Não há ferramenta de transcrição/análise de vídeo nem LLM configurado no runtime do bot; integrações opcionais devem declarar essa ausência.
