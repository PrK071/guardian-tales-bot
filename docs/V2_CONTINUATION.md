# Continuação V2 — 08/11/2026

Nenhuma fase real concluída; não marcar meta completa. Arquivos E:\GuardianTalesBot. Sem subagentes autorizados.

## Execução atual

Calibração real ativa: sessão exec30272, script evaluations/v2/lantern_calibration.py --phase arrive, pasta data/v2/v2_lantern_calibration_7150388e43af4628. Servidor principal desligado. Poll da mesma sessão; não iniciar controlador concorrente. Sessão62269/cface23508d84a6d ENCERRADA após199,057s por vida baixa nos espinhos (~20-23%).

Mudanças posteriores importantes: cognitive/hazard_control.py escolhe parada150px além da coluna observada, entre colunas espaçadas~337px, sem alegar ausência de colisão. Duração baseada em132px/300ms observados numa ação down do cface; hipótese de velocidade0,44px/ms. Navegação horizontal não alterna mais cima/baixo para fugir de coluna vertical. Reconsulta geometria no pre-input e limita ao trecho reto observado. Pulsos fixed_hold também limitados a reference_distance/0,0592*0,90 para não passar da curva; esta última linha foi acrescentada após suíte59/59 e será validada na execução atual. Guardas imediatas de vida<25% e ator ausente retêm movimento; seis testes de endpoints/guardas passaram. MSI foi ativado em primeiro plano via skill Computer Use; captura Windows continua falhando com timeout, ADB funciona. Não alterar Eco Mode às cegas: configuração só informa limite5FPS, não comprova modo ativo.

Novo reset observado: v2_preparation_724c616712574707/report.json. Relatório final regenerado com59/59 V2 ezero conclusões. Não repetir regressões completas sem mudança relevante.

O MSI reaberto estava no acampamento. ADB reconectado. Preparação 6368d8e306544534 entrou na Passagem 1. Calibração bcd0a8a339db4292 parou numa captura Android cinza; até três reobservações sem entrada agora implementadas e testadas. Calibração 64f19690f25f4c65 (376,387s) interrompida deliberadamente para remover ciclo duplicado de mapa na chegada. STOP foi removido após pausa. Calibração 8617713a0ec24422 (134,035s) parou por vida ~21% nos espinhos. Não baixar limiar de saúde para forçar avanço.

Reset real: v2_preparation_2d97b86e35f744bd. Calibração segura v2_joystick_calibration_eb3322a2ece34a78: toque mantido no extremo do joystick por900ms avançou53,19 pixels de referência, versus~27 com swipe anterior. FastSession agora usa fixed_hold; ADB.move da V1 preservado. A calibração ativa já usa isso. Removidas capturas duplicadas: transition reutiliza frame<0,20s; navegação usa frame da transição; conversa usa frame<0,50s. Dez cenários principais passaram após alteração; fazer regressão completa após próximos ajustes.

## Próximos passos

- Poll62269. Se chegar, lantern_calibration.py --phase approach; depois --phase pickup. Ambos pausam no final. Inspecionar imagem/lantern.jsonl em caso de falha; sem toque repetido cego.
- Coleta exige affordance, sumiço do chão, template acima do ator, glyph alterado e acompanhamento após movimento. Código existe, coleta real ainda NÃO validada.
- --phase ignite implementada, NÃO executada. Reconcilia glyph de arremesso da coleta real; aproxima fonte e exige fogo transportado longe da fonte fixa. Ajustar somente com evidência atual.
- Ainda falta acender demais lanternas, verificar passagem da barreira, integrar ao StageRunner ANTES da exclusão genérica de fronteira, combater boss e observar saída/resultado. Só tentativa desde nascimento até dois resultados OCR pode contar; reproduzir depois.

## Pesquisa e memória já prontas

knowledge/v2_lantern_research.json, memória research/reported memory_b8b83229088d44f6. Wiki Passage1 e vídeo https://www.youtube.com/watch?v=P8Kob7UhlNs realmente visto:1:29 sala/braseiro;1:32 carregado/throw glyph;1:36 fogo carregado/lanterna inferior direita/pedra queimando;1:41 boss depois da barreira. CUA já finalizada; não repetir pesquisa/browser sem necessidade.

assets/v2 contém portable_brazier.png e standing_lantern_unlit.png, com proveniência. Filtro cinza corrigido para fração real12,5%; barreira laranja não é chama; proximidade não descarta braseiro. Três testes históricos passaram.

evaluations/v2/object-vantage-replay.json e SQLite v2_object_vantage: braseiro visto do ator referência[409,684] até[409,755], fonte esquerda vista de[409,710]. Posições são do ator observado, não coordenadas globais do objeto; retornar exige nova observação.

Âncora atual já migrada com spawn_point, identidade bde52d502e873032794e805d93eb1ece6bcc04c7003588536d2bc90a175bef99. Não repetir migração.

## Testes, métricas e entrega

V1 última regressão45/45. V2 última suíte completa53/53; controle/capturas alterados depois passaram dez cenários principais e compilação. Não contar mocks como jogo.

Seis trials encerrados anteriores:3 iniciais,3 retomados,0 conclusões,752,623s,289 ações,34 movimentos alinhados. Combate real trial99d348c7cb44486e: ataques e três ausências de barras; depois barreira imóvel. Qwen perfilado nove vezes, média full37,865s/mínimo10,678s/seletivo20,497s, mesmo modelo. Não repetir profiling.

evaluations/v2/summarize.py agora separa calibrações de lanternas; write_report.py gera os11 tópicos de docs/V2_END_TO_END_REPORT.md. Regenerar após novos relatórios encerrados e atualizar limitações se coleta/fogo forem comprovados. Relatório não declara conclusão.

Python tools/python/python.exe -X utf8; ADB tools/platform-tools/adb.exe; serial127.0.0.1:5555;1600x900. Calibrações só com servidor parado. STOP em data/v2/STOP; remover apenas após pausa/encerramento. Main via bot.py --no-browser oculto; client.py stage_v2 100 900.
