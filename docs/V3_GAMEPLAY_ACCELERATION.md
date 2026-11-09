# V3 — aceleração de gameplay


## Diagnóstico dos gargalos originais

A V2 já registra zero chamadas ao Qwen no loop tático. O principal gargalo é o ciclo de captura, planejamento local, transição de mapa e comando curto. No trial `5aa90fc7327340cf`,42 movimentos tiveram duração média541,7ms. No trial `99d348c7cb44486e`,31 movimentos tiveram média448,7ms; os três intervalos observacionais entre ataques tiveram média1.927,3ms e máximo/p95 de4.166,3ms. Esses intervalos vêm dos timestamps de observação e não medem exatamente o instante físico de entrada.

Medição atual sem comandos no jogo: oito `shell echo`, média66.63ms/p9584.49ms; oito capturas brutas, média334.39ms/p95472.91ms. Evidência: `evaluations/v3/baseline.json`. A captura por comando e a abertura repetida do mapa são limitações de software. Colisão física com NPC e redução de movimento durante golpe são observações do jogo que exigem plano/controle adequados.

## Mudanças implementadas

Backend persistente `ScrcpyTouch`, servidor oficial3.3.2 com SHA256 verificado contra o instalador da mesma tag; sem root, alteração de arquivos do jogo ou hooks no processo. ADB continua responsável pelo transporte inicial e captura; cada toque posterior usa o socket de controle, com ponteiros distintos. Protocolo e fontes estão em `tools/scrcpy/manifest.json` e `data/v3/research/`. [Fonte oficial](https://github.com/Genymobile/scrcpy/tree/v3.3.2).

`ContinuousActions` oferece `move_hold`, `attack_hold`, `use_skill`, `move_attack_hold` e `execute_sequence`. A duração é explícita, com teto de segurança30s por ação; valores de gameplay devem vir de calibração e geometria. Um timer libera o toque no prazo, mesmo se o observador estiver lento. Um watcher separado trata cancelamento/STOP. `finally` libera os ponteiros; falhas de envio/limpeza são registradas, sem fingir confirmação do Android. Sequências adjacentes compatíveis são agrupadas sem soltar o controle entre microações.

`LiveObserver` captura em paralelo à entrada; o controlador consulta o último estado sem esperar por cada captura. Frames muito antigos ou falhas interrompem a ação. A mesma memória SQLite e o lease de executor V1/V2 são reutilizados. `StageV3Runner` está integrado à fila existente, ao cliente `stage_v3` e ao botão V3 do painel. O progresso de cada objetivo fica na memória persistente e o botão Parar usa o cancelamento existente.

## Benchmarks antes/depois

Primeiras calibrações no mesmo corredor inicial: caminhada1000ms deslocou59,57 pixels de referência; corrida1000ms deslocou74,47. São uma amostra por modo, com retorno ao nascimento confirmado: ganho de deslocamento de aproximadamente25% nesse ensaio, sem extrapolação para toda a fase. Não são metros nem taxa de conclusão de objetivos.

Envio pelo socket: {'n': 51, 'mean': 0.11200392128004893, 'p95': 0.48160000005736947}. Erro absoluto da duração mantida nas ações que chegaram ao prazo: {'n': 15, 'mean': 3.014210758904964, 'p95': 20.1325000016368}. São tempos locais de envio/liberação; o protocolo não fornece ACK de cada toque. Deslocamento é confirmado separadamente pelo mapa alinhado.

Benchmark controlado: rota inicial de80 pixels de referência, tolerância de6 pixels, mesma região, retorno observado entre amostras, três repetições por modo. Tempo inclui planejamento, transições e confirmação do endpoint; startup do canal persistente é separado. Ganho V2/contínuo: 2.560073012417253 vezes. Evidência: `data\v3\v3_route_benchmark_4b6590bd1e994e9e\report.json`.

| Modo | Tempo médio(s) | P95(s) | Progresso(px ref/min) | Objetivos atingidos | Comandos de movimento |
| --- | --- | --- | --- | --- | --- |
| v2 | 12.480 | 13.273 | 373.96 | 3/3 | 2.0 |
| continuous | 4.875 | 4.971 | 960.44 | 3/3 | 1.0 |
| run | 4.933 | 5.090 | 979.61 | 3/3 | 1.0 |

Nove chegadas dentro da tolerância demonstram ganho nessa região; não demonstram navegação universal. A V2 teve intervalos de aproximadamente4,77–5,42s entre seus dois comandos. O modo contínuo usa um comando por caso, portanto não tem amostra de intervalo entre comandos nesse trajeto; o overhead de verificação continua no tempo total. Corrida não demonstrou melhoria no tempo total sobre a caminhada contínua nessa amostra curta. N=3 por modo; p95 nearest rank é o máximo. Cancelamento real, da solicitação ao envio de UP: {'n': 1, 'mean': 7.398200003081001, 'p95': 7.398200003081001}; liberação recebida pelo Android não tem ACK.

Combates equivalentes são descritos na atualização de medições abaixo. Taxas de colisão em regiões complexas continuam sem amostra suficiente. Ações por chamada ao LLM são não aplicáveis quando o denominador ézero; registrar ações executadas e chamadas separadamente.

## Resultados de navegação

| Execução | Operação | Duração pedida(ms) | Progresso de referência(px) | Mapa confirmou | Retorno ao nascimento | Erro |
| --- | --- | --- | --- | --- | --- | --- |
| v3_input_probe_175b38f9a0cc40f3 | sequence | 2000.0 | 102.12765957446811 | True | True | — |
| v3_input_probe_521ecfbba9594c09 | run | 1000 | 74.46808510638289 | True | True | — |
| v3_input_probe_52b07afa50884c11 | sequence | 2000.0 | 102.12765957446811 | True | True | — |
| v3_input_probe_6e69dadd34664215 | combined | None | None | None | None | ValueError: No observed floor component in the pause map; pause: Cannot transition from unrecognized screen: unknown |
| v3_input_probe_72f5c24ddb51463c | move | 1000 | 59.57446808510633 | True | True | — |
| v3_input_probe_7fa59490b0234bcc | combined | 1000 | 4.255319148936223 | True | None | RuntimeError: Roundtrip is restricted to the observed safe initial vertical corridor |
| v3_input_probe_8548cd43623e45a2 | connect | None | None | None | None | — |
| v3_input_probe_9da431a7c30b4e54 | interrupt | None | 25.531914893617 | True | None | — |
| v3_input_probe_b725dce78b654f54 | restore | 448.85021571564886 | 25.531914893617 | True | True | — |
| v3_input_probe_b9f3a7d32e594303 | restore | 1556.6811621475802 | 91.48936170212755 | True | True | — |
| v3_input_probe_f325d51313eb489b | attack | 2500 | 91.48936170212755 | True | None | — |

O teste de2s atingiu o NPC no eixo central, limitando o avanço a aproximadamente102px. Agrupar os comandos reduziu transições de toque, mas esse caso não demonstrou aumento de distância: a colisão limita a medição. A aproximação contextual do NPC agora pode interromper a calibração como checkpoint.

## Resultados de combate

`CombatController` implementa estados de detecção, aproximação, engajamento, ataque mantido, orientação após ausência de efeito, habilidade condicionada a disponibilidade observada, recuperação, retirada curta por piso visível e fim de encontro. Cada golpe normal dispensa inferência. Três observações distintas sem inimigo, após presença observada, são exigidas para confirmar apenas o fim do combate visível.

O teste simultâneo de movimento+ataque manteve ponteiros distintos por~1s, mas avançou apenas4,26px. Isso é muito inferior à caminhada isolada e não autoriza assumir que atacar correndo seja eficiente para este personagem. Um ataque mantido isolado durou2501ms com um DOWN/UP e animações observadas; também avançou91,49px. Esse deslocamento é efeito observado durante ataque, não métrica de navegação. O encontro real `v3_prefix_probe_a4e4e2e39c094194` terminou em12,678s de sessão, com4 movimentos e3 períodos de ataque. Três frames sem barras pequenas ou barra focada confirmam apenas o fim do encontro visível. Não é comparação equivalente nem medição de DPS solo: Loraine participa.

No teste integrado, a barra pequena do slime piscou durante um golpe. O checkpoint bruto impediu o falso registro de fim de combate. A percepção agora reconhece a barra focada no topo e procura a borda escura logo abaixo do preenchimento destacado. Contadores do HUD e pixels de caverna permanecem excluídos. Três ausências no vídeo exigem confirmação bruta; se ainda houver inimigo, a FSM volta a observar e combater. Esses casos reais viraram regressões de percepção.

Habilidade disponível, esquiva e retirada ainda não foram validadas no jogo. O starter atual mostra botões de habilidade inativos; não há template de prontidão validado.

## Integração de walkthroughs

Pesquisa e memória V2 preservadas, incluindo guia da Passagem1 e quadros de vídeo observados. `WalkthroughPlanner` compila9 objetivos tipados antes de iniciar: entrada, desvio do NPC, corredor norte, primeiro encontro, ramificação, sala do braseiro, lanternas, encontro final e saída. Cache inclui fase, modo observado, versão do jogo e referência do mapa. Uma tentativa de pesquisa insuficiente fica em cache por24h. O cursor sobrevive a reinício; entrada nova verificada o reinicia. Divergência registra a fonte e a observação sem avançar o objetivo. Os3 primeiros objetivos têm coordenadas locais verificadas; os demais exigem reconhecimento atual de marcos. Fontes externas permanecem reportadas, nunca código executável.


## Inferências desnecessárias

Nenhuma chamada ao modelo ocorre nos controladores contínuos. A V2 já tinha esse resultado; a V3 não declara uma redução adicional de chamadas que não ocorreu. O perfil anterior do Qwen é reutilizado: mesmo modelo, pesos e orçamento. Planejamento estratégico e replanejamento de desconhecidos continuam separados das entradas locais.

## Testes, falhas e limitações remanescentes

Testes V3: 119/119. Cobrem protocolo, dedos distintos, liberação em exceção/cancelamento/prazo durante captura lenta, guarda da corrida, sequências, FSM de combate, três ausências distintas, recuperação, geometrias com parede e mapa histórico do nascimento. Não são prova de combate real. Resultados e logs: `evaluations/v3/tests.json`.

O jogo apresentou conexão perdida antes de um teste; comandos foram retidos e a reconexão observada devolveu a tela pausada. O backend não tenta contornar telas desconhecidas. Se a conexão com Android cair, envio de UP não equivale a confirmação recebida; o relatório preserva a incerteza.


## Vídeo e custo de observação

O vídeo usa o mesmo servidor scrcpy, H.264 e PyAV19.0.2. O wheel oficial foi verificado por SHA256 e instalado somente no Python em E:. Fonte: [PyAV](https://pyav.org/docs/stable/overview/installation.html). O teste passivo `v3_video_probe_f6446820fc1f420f` recebeu162 frames: intervalo médio49,92ms, p9575,18ms e decodificação média4,12ms. Não enviou entradas. O mapa extraído do vídeo e da imagem bruta deu a mesma posição [944,300]. Isto não mede a latência absoluta Android→host.

O encoder anuncia1600×904. A imagem é normalizada para1600×900, e os toques são convertidos para a geometria anunciada, como exige o protocolo. O primeiro ensaio integrado enviou a geometria errada e não moveu o personagem; o mapa reteve o checkpoint. O erro foi corrigido e tem teste de regressão.

Em10 replays do mesmo frame de combate, visão espacial custou84,39ms e reconhecimento de lanternas117,48ms em média. A observação contínua dispensa essa busca de objetos; os checkpoints brutos continuam fazendo-a. Essa é medição de custo por componente, sem alegar ganho de combate por extrapolação. Frames mantêm sequência, PTS e timestamp de recebimento; imagens antigas param o controle.

## Comparação de combate e integração

Mesmo primeiro encontro, conta, equipe e preparação por rota comum. Tempos incluem a retomada da pausa e observação inicial; startup do backend ocorre ainda pausado. A confirmação final é bruta. A contribuição automática da NPC e o preenchimento inicial das barras são registrados; esta comparação mede o encontro da equipe.

| Modo | Casos medidos | Fins verificados | Média válida(s) | P95 válido(s) |
| --- | --- | --- | --- | --- |
| v2 | 3 | 2 | 14.801 | 16.592 |
| v3_video | 2 | 2 | 14.665 | 15.187 |

Preparações sem inimigo confirmado e leituras OCR sem identidade suficiente não entram na média de combate. A média válida inclui apenas fins confirmados; retorno com inimigo ainda vivo é falha, nunca tempo de conclusão. Resultados estão separados por série em `combat_cohorts`, com posição e área vermelha iniciais. Dados completos: `evaluations/v3/metrics.json` e `data/v3/v3_combat_benchmark_*/cases.json`.

| Trial integrado | Cursor | Ciclos | Chamadas Qwen | Resultado |
| --- | --- | --- | --- | --- |
| v3_trial_042e8212b28a46f5 | 6 | 18 | 0 | blocked: RuntimeError: Lantern approach stalled twice; no repeated blind movement |
| v3_trial_ee5dd3bad6204536 | 6 | 12 | 0 | blocked: RuntimeError: Room checkpoint did not improve across the bounded visual sequence |


## Latência, decisões e limites da medição

| Modo da rota | Planejamento local médio(ms) | P95(ms) | Planos locais/min | Qwen/min |
| --- | --- | --- | --- | --- |
| v2 | 193.24 | 202.69 | 9.63 | 0.0 |
| continuous | 19.60 | 22.95 | 12.31 | 0.0 |
| run | 22.78 | 31.95 | 12.17 | 0.0 |

Um plano local corresponde a uma escolha geométrica de rota, não a uma inferência. Há2 planos/movimentos por travessia na V2 e1 no modo contínuo. A taxa por minuto pode aumentar com a velocidade mesmo quando há menos decisões por travessia. As durações históricas de448,7/541,7ms são pedidos ao Android; os tempos locais de DOWN/UP da V3 também não são ACK físico.



## Ambiente de ensaio e validações restantes

Em2026-11-08 foi conferida a [política operacional oficial](https://guardiantales.com/src/operation.htm), seção4. Após uma suspensão para esclarecer o ambiente, o usuário confirmou explicitamente: Tenho ambiente autorizado. Essa pendência está resolvida; os testes reais foram retomados no ambiente informado. O usuário também determinou continuidade autônoma, sem novas perguntas ou permissões rotineiras.



## Validação final e correções integradas

Atualização: 2026-11-09T08:07:10. Conclusões reais de saída reconciliadas: 2. Em `data/v3/v3_trial_9284f3ddf8044ce2/exit-reconciliation.json`, duas capturas brutas independentes mostram a recompensa de 50 gemas e “Etapa Completada!”. O cursor e as tarefas SQLite foram concluídos com essa prova, sem reenviar interação. O OCR sem espaços e `Observation.frame_path` agora são tratados corretamente. A primeira conclusão teve calibrações, correções e retomadas pelo agente; não representa um ensaio único autônomo desde o nascimento.

O corredor norte real foi atravessado em um hold de 3.471,97ms, com 205,319 pixels de referência, erro final3,84px e tempo total9,361s (`v3_trial_042e8212b28a46f5`). Os trechos agora usam apenas eixos e diagonais45° suportados: o jogo mostrou que vetores rasos podiam mover somente um eixo. Linha de visão e margem são verificadas para cada perna. O horizonte curto permanece para região desconhecida, sem limitar artificialmente corredores conhecidos.

Mapa recém-capturado pode ser reutilizado por até4s se nenhuma entrada ocorreu. Antes de uma interação, a observação de jogo com ator válido por até350ms evita captura redundante. No mapa completo após o primeiro clear, o pin ocultava piso e favorecia uma sala parecida; o alinhamento agora compara candidatos excluindo somente o retângulo observado do ícone e mantém limiar e separação de confiança. O spawn é confirmado pela referência geométrica, não pelo fundo do bounding box de todo o mapa.

`SpatialVision.floor_mask` elimina chamadas completas ao detector de entidades apenas para obter piso. Capacetes são refinados quando necessário e fragmentos reais sustentam a pose durante oclusão pela NPC. Carregamento usa objeto/seta e calibração persistente; quando falta prova, o movimento para. Replay pareado dos mesmos4frames,3repetições por condição (12 por célula), sem entrada no jogo:

| Pipeline | Antes média/p95(ms) | Depois média/p95(ms) |
| --- | --- | --- |
| Sem item | 279.93/385.75 | 113.00/196.25 |
| Carregando | 263.78/386.06 | 64.04/105.06 |

Mede somente o componente de visão, excluindo captura, entrada e matcher da pose carregada. Hashes, ordem alternada e casos: `evaluations/v3/actor-perception-benchmark.json`. Não extrapola aceleração integral da fase.

## Puzzle, guia e saída — resultados reais

O fluxo integrado executa luva→pickup→ignição→duas vistas das lanternas→barreira→encontro final→saída, com recuperação do cursor por entrada. A luva removeu os dois tiles; o primeiro reduziu6313pixels verdes para0 e expôs78,6% de piso. O segundo teve10564→16 e74,85% de piso (`c7253326189c4557/tile-reconciliation.json`); a verificação inicialmente escolheu a rocha errada, e a falha original foi preservada ao reconciliar o tile realmente removido.

Ignição: `v3_lantern_probe_186284eed6494f66`, duas observações afastadas526,69pixels de referência da fonte. Luz superior direita: `a06fbb49f6ea4350`; inferior direita final: `63446d2af4c24447`, duas imagens independentes com alvo registrado no mapa. Quatro lanternas ficaram acesas. Em `0b84e4b080de4892`, duas imagens comprovaram painel removido/piso90,5%, e o mapa confirmou travessia para[441,95,812,16], além de toda a borda anterior. O objetivo não depende só da presença de fogo e fica ligado ao token da entrada atual.

O Orc foi observado antes do arremesso e ausente em três capturas posteriores, incluindo uma bruta, sem comando de personagem entre essas confirmações (`v3_trial_7be9bd0f5cb64779/final-encounter-reconciliation.json`). Isso não é uma medição de duração/DPS. Combate com item reconcilia a pose antes da detecção, solta o objeto com prova e usa presença fresca anterior se o inimigo morrer durante a soltura; ainda exige as três ausências e raw independente.

A casa branca no corredor sul exige INTERAÇÃO. O bot observa casa+glyph antes de um único toque e exige duas observações reais de resultado. Estrela preenchida isolada não comprova a partida atual: o caminho alternativo pelo mapa exige entrada, puzzle/encontro, casa e ação emitida; estrela vazia é regressão negativa. O guia em vídeo P8Kob7UhlNs foi observado na saída1:55 e retorno ao mapa1:58. Guias ficam como relato e checkpoints atuais decidem a execução. O compilador permanece específico de Passagem1 normal; outras fases/modos não recebem rota inventada.

## Aproximação de pedra com personagem encoberto

No ensaio fresco `ebd17a2d61694c04`, a NPC encobriu o cavaleiro e a leitura local do pé ficou abaixo do piso. A alternativa usa uma lanterna fixa atualmente reconhecida, sua referência verificada e a posição independente do mapa. Escolhe a lateral com piso livre, mantém o limiar de folga, exige chegada medida e o ícone atual da luva. A primeira tentativa `6a933031abef4d9c` recusou um ponto próximo demais da borda; a escolha adaptativa de afastamento corrigiu essa recusa sem reduzir a folga exigida.

Na retomada `a0c41cef618c410b`, a remoção foi confirmada:10272→549pixels de pedra,81,02% de piso visível. Não é medição de aceleração nem prova de conclusão integral. `evaluations/v3/registered-stone-regression.json` preserva a geometria e as evidências. A próxima falha foi a busca de uma tocha cortada pelo limite esquerdo da visão; a busca agora inclui a região abaixo do minimapa, mantendo os limiares de correspondência e eliminando duplicatas. Replays das duas situações estão versionados em `evaluations/v3/fixtures/`.

A navegação da sala pode usar uma única recuperação para dentro de um tile removido e visualmente alinhado. Ela não repete indefinidamente a recuperação e não ignora pedras atuais. Depois da luva, o fluxo retorna ao ponto de observação planejado antes de procurar a tocha: a investida pode colocá-la sob o joystick virtual, onde a aparência fica encoberta. As falhas originais de reaproximação permanecem nos trials; esses ajustes não recebem ganho de velocidade por extrapolação.

Na retomada `ec1f806d32c44455`, a tocha ficou adjacente ao personagem junto à parede, mas o planejamento local recusou a máscara do pé encoberto. Esse caso permite uma única virada de80ms somente com o objeto atualmente reconhecido dentro do alcance. Ela não emite pickup: uma nova observação ainda precisa comprovar mão/bubble e a transferência subsequente. O replay negativo confirma que a ausência persistente do ícone não causa viradas ou interações repetidas.

Na retomada `1b64afbd353d4625`, pickup, permanência do item após deslocamento, última lanterna, travessia e encontro final foram confirmados. A saída entrou em carregamento por mais de10s; a primeira observação válida do mapa foi registrada23,97s após a interação, fora do antigo prazo. A verificação agora espera até45s, sem novos comandos. A estrela completa tem núcleo branco nos pixels brutos: a antiga máscara só dourada dividia sua silhueta em duas regiões pequenas, embora o JPEG parecesse reconhecível. A nova máscara une dourado e núcleo claro, exige85% de preenchimento, pelo menos70pixels dourados e centro claro; a estrela vazia continua sendo rejeitada.

A reconciliação dessa entrada confirmou duas imagens independentes do mapa em12,313s e enviou zero comandos. Cursor9/9, com o report bloqueado original preservado em `v3_trial_1b64afbd353d4625/exit-reconciliation.json`. Isso é uma execução concluída por retomadas e correções; não demonstra uma partida integral autônoma com a versão final, nem um ganho de tempo integral.

O ensaio fresco `19f75214f5fe4c78` chegou a6/9 em428,417s e parou na confirmação da luva. A área antiga era centrada no personagem e atravessava duas colunas de um grupo em L: parte da pedra vizinha intacta entrava na medição. A seleção agora usa a coluna observada mais próxima que realmente contém pedra; mantém os limiares de remoção, piso, visibilidade e alinhamento. O replay antes/depois desse caso passa com a coluna correta e permanece separado de uma nova validação ao vivo. A primeira recusa do pickup foi recuperada internamente por reconciliação visual, sem repetir a interação.

O ensaio fresco seguinte `ee5dd3bad6204536`, com a seleção corrigida, chegou a6/9 em543,027s. Confirmou o pickup, recuperou autonomamente um encontro intermediário com item e executou a ignição. Parou no puzzle quando o mapa não confirmou melhora no retorno ao checkpoint da sala. O report original permanece em `data/v3/v3_trial_ee5dd3bad6204536/report.json`; esse ensaio não comprovou conclusão integral autônoma. Suas falhas de navegação e de alinhamento ficam separadas do ganho medido no corredor conhecido.

A análise do retorno mostrou um desvio válido: o mapa passou de[379,55;756,04] para[378,14;740,55] ao contornar a pedra antes de seguir para[426;775]. A distância euclidiana cresceu temporariamente. A guarda antiga exigia aproximação em linha reta e recusava esse caminho. Agora, após uma sequência escolhida pelo piso observado, uma posição nova confirmada no mapa pode validar o desvio; revisitar uma posição a até4pixels de referência continua sendo recusado e o orçamento de16ações permanece. Isso não conclui o objetivo: a chegada ainda exige o endpoint medido. O replay real e o teste negativo de retorno estão em `evaluations/v3/fixtures/room-detour/`; não são medição de ganho de tempo no jogo.

O pickup seguinte expôs outra diferença: o JPEG diagnóstico mudava7615pixels da máscara de piso e não reproduzia a recusa dos pixels brutos. Falhas V3 agora guardam PNG com hash dos pixels, sem acrescentar gravação lossless ao caminho normal. O planejador local usa uma alternativa de grade fina somente quando o extrator anterior não encontra trecho executável; mantém28pixels de folga e verifica também qualquer extensão ao mínimo de80ms. O replay lossless passa. No teste real `v3_lantern_probe_0be178eec14a4731`, dois movimentos completaram a aproximação, seguidos de transferência e acompanhamento verificados. O ensaio anterior no mesmo ponto parou sem mover. Isso comprova correção desse bloqueio, não uma razão de aceleração temporal nem conclusão da fase. Dados: `evaluations/v3/raw-corner-regression.json`.

## Métricas de aceitação e limites

Chamadas Qwen/min =0 antes e depois nos loops medidos. Ações/LLM =N/A com denominador0, sem alegar redução adicional. Objetivos da rota =9/9; falhas de chegada =0/9 (erro<=6px), sem perda de vida observada. Isso é proxy definido, não medição física universal de colisões. A colisão com NPC limitou dois ensaios específicos de2s; em regiões complexas, falhas/recusas ficam preservadas nos reports.

Ensaio integrado final `data\v3\v3_trial_ee5dd3bad6204536\report.json`: resultado `blocked`, cursor 6/9, nascimento verificado True, 6 objetivos em 543.027s, 0.663 objetivos/min; 12 ciclos. Motivo: RuntimeError: Room checkpoint did not improve across the bounded visual sequence.

Comparação de combate selecionada: `v3_combat_benchmark_f7859decec7c4428`. Não misturar séries antigas com código diferente. Tempos de falha não contam como conclusão. Os JSONs preservam entradas iniciais, raw final, ações e erros.

Comparação temporal estrita usa somente repetições com ambos os controladores concluídos: [0, 1]. V2: {'n': 2, 'mean': 14.800648899996304, 'p95': 16.59210819999862}; V3: {'n': 2, 'mean': 14.665353700002015, 'p95': 15.18651079999836} (segundos). A terceira V2 sem conclusão não recebe tempo fictício e não forma par temporal. Diferença V3−V2 por par: {'n': 2, 'mean': -0.13529519999428885, 'p95': 1.135007000011683}. Amostra pequena com contribuição da NPC; não demonstra ganho geral de combate.

Falha de combate v2, repetição2: RuntimeError: Controlled character absent in immediate pre-input observation; movement withheld. Tempo até falha: indisponível; Controller raised during combat before the old harness stored elapsed timing; failure retained, no completion duration invented..

Taxa integral de conclusão não é extrapolada de uma fase. Habilidade pronta, esquiva e retirada ainda carecem de ensaio real apropriado; starter tem botões inativos. Nenhum novo modelo, agente ou framework foi introduzido. Preservados hierarquia, SQLite, lease, STOP e fila V1/V2. Telas desconhecidas ou perda de conexão interrompem o executor; não há compra, root ou hook.

Verificação final: V3 119/119; legado 45/45; V2 59/59. JSONs e logs guardam falhas completas; fixtures não provam gameplay novo.

Duração real dos holds de movimento no ensaio de rota, incluindo retornos entre amostras: {'n': 15, 'mean': 1274.7026133331626, 'p95': 1397.289799999271} (ms). Preparações da série final sem tempo de combate medido: 2; não entram na média de conclusão. Falha de ação é reportada pelo endpoint fora da tolerância ou combate sem prova bruta, não por cada interrupção preventiva de segurança.
