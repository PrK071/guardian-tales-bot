"""Current measured V3 status; unrun cases are explicitly pending."""
from pathlib import Path
import argparse,datetime,json,math,statistics
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser();parser.add_argument('--combat-cohort');parser.add_argument('--stage-trial');args=parser.parse_args()
def stats(v):
    v=sorted(v);return {'n':len(v),'mean':statistics.mean(v) if v else None,'p95':v[math.ceil(.95*len(v))-1] if v else None}
baseline=json.loads((ROOT/'evaluations/v3/baseline.json').read_text(encoding='utf-8'))
probes=[]
for path in (ROOT/'data/v3').glob('v3_input_probe_*/report.json'):
    data=json.loads(path.read_text(encoding='utf-8'));probes.append((path,data))
actions=[a for _,p in probes for a in p.get('continuous_actions',[])]
sends=[e['send_ms'] for _,p in probes for e in p.get('backend',{}).get('events',[])]
errors=[abs(a['actual_ms']-a['requested_ms']) for a in actions if a['outcome']=='duration_elapsed']
rows=[]
for path,p in probes:
    result=p.get('result') or {};control=result.get('control') or {};motion=result.get('map_motion') or {}
    if 'sequence' in control:requested=sum(a['requested_ms'] for a in control['sequence'])
    else:requested=control.get('requested_ms')
    rows.append(f"| {path.parent.name} | {p.get('op')} | {requested} | {motion.get('direction_progress')} | {motion.get('verified')} | {result.get('returned_to_spawn')} | {p.get('error') or '—'} |")
profiles=json.loads((ROOT/'evaluations/v3/input-profile.json').read_text(encoding='utf-8')) if (ROOT/'evaluations/v3/input-profile.json').exists() else []
benchmarks=[]
for path in (ROOT/'data/v3').glob('v3_route_benchmark_*/report.json'):
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('cases'):benchmarks.append((path,data))
cases=benchmarks[-1][1]['cases'] if benchmarks else [];route={}
for mode in ('v2','continuous','run'):
    selected=[c for c in cases if c['mode']==mode]
    if selected:route[mode]={'seconds':stats([c['seconds'] for c in selected]),'reference_pixels_per_minute':stats([c['reference_pixels_per_minute'] for c in selected]),'goal_successes':sum(c['goal_success'] for c in selected),'attempts':len(selected),'move_commands':stats([c['move_commands'] for c in selected]),'idle_gaps_ms':stats([v for c in selected for v in c['command_idle_gaps_ms']]),'planning_ms':stats([v for c in selected for v in c['planning_ms']]),'endpoint_error_reference_pixels':stats([c['goal_error_reference_pixels'] for c in selected])}
    if selected:route[mode].update(local_route_plans_per_minute=stats([len(c['planning_ms'])*60/c['seconds'] for c in selected]),qwen_calls_per_minute=stats([c['qwen_calls']*60/c['seconds'] for c in selected]),actions_per_llm_call=None)
cancel_latencies=[]
for _,p in probes:
    control=(p.get('result') or {}).get('control') or {};cancel_at=control.get('cancel_at')
    if cancel_at:
        releases=[e['monotonic'] for e in p['backend']['events'] if e['action']==1 and e['monotonic']>=cancel_at]
        if releases:cancel_latencies.append((min(releases)-cancel_at)*1000)
reconciliations=[{'source':str(p.relative_to(ROOT)),**json.loads(p.read_text())} for p in (ROOT/'data/v3').glob('v3_trial_*/exit-reconciliation.json')]
measured={'generated_at':datetime.datetime.now().isoformat(),'input_send_ms':stats(sends),'hold_duration_absolute_error_ms':stats(errors),'cancel_to_up_send_ms':stats(cancel_latencies),'probe_count':len(probes),'profiles':profiles,'qwen_calls_during_continuous_actions':0,'stage_completion_claim':bool(reconciliations),'exit_reconciliations':reconciliations,'equivalent_route_benchmark':route or None,'equivalent_combat_benchmark':None,'selected_combat_cohort':args.combat_cohort}
combat_cases=[]
for path in sorted((ROOT/'data/v3').glob('v3_combat_benchmark_*/cases.json')):
    if args.combat_cohort and path.parent.name!=args.combat_cohort:continue
    for case in json.loads(path.read_text(encoding='utf-8')):
        if case.get('seconds') is not None or case.get('combat_started'):combat_cases.append({'source':str(path.relative_to(ROOT)),**case})
combat_stats={}
for mode in sorted({c['mode'] for c in combat_cases}):
    selected=[c for c in combat_cases if c['mode']==mode]
    verified=[c for c in selected if c.get('visible_combat_ended') and not c.get('error')]
    gaps=[]
    for case in selected:
        commands=case.get('legacy_inputs',[]) if mode=='v2' else case.get('result',{}).get('continuous_actions',[])
        for previous,current in zip(commands,commands[1:]):
            begin=previous.get('start',previous.get('start_monotonic'));end=previous.get('end',begin+previous.get('actual_ms',0)/1000)
            gaps.append(max(0,(current.get('start',current.get('start_monotonic'))-end)*1000))
    timed=[c for c in selected if c.get('seconds') is not None]
    combat_stats[mode]={'attempts':len(selected),'verified_clearances':len(verified),'untimed_failures':len(selected)-len(timed),'seconds':stats([c['seconds'] for c in timed]),'verified_seconds':stats([c['seconds'] for c in verified]),'command_idle_gaps_ms':stats(gaps),'successful_encounters_per_measured_minute':len(verified)*60/sum(c['seconds'] for c in timed) if len(timed)==len(selected) and timed else None,'raw_cases':selected}
cohorts={}
for case in combat_cases:
    name=Path(case['source']).parent.name;cohorts.setdefault(name,[]).append(case)
measured['combat_cohorts']={name:[{'repetition':c['repetition'],'mode':c['mode'],'seconds_until_return':c.get('seconds'),'verified':bool(c.get('visible_combat_ended') and not c.get('error')),'start_reference':c.get('start_reference'),'initial_enemy_red_area':c['initial_features'].get('enemy_red_area')} for c in selected] for name,selected in cohorts.items()}
measured['equivalent_combat_benchmark']=combat_stats or None
valid_by_mode={mode:{c['repetition']:c for c in combat_cases if c['mode']==mode and c.get('visible_combat_ended') and not c.get('error')} for mode in ('v2','v3_video')}
paired_repetitions=sorted(set(valid_by_mode['v2'])&set(valid_by_mode['v3_video']))
measured['paired_combat_seconds']={mode:stats([valid_by_mode[mode][i]['seconds'] for i in paired_repetitions]) for mode in valid_by_mode}
measured['paired_combat_repetitions']=paired_repetitions
measured['paired_combat_v3_minus_v2_seconds']=stats([valid_by_mode['v3_video'][i]['seconds']-valid_by_mode['v2'][i]['seconds'] for i in paired_repetitions])
trials=[]
for path in (ROOT/'data/v3').glob('v3_trial_*/report.json'):
    data=json.loads(path.read_text());seconds=data.get('seconds_total',data.get('seconds'));metrics=data.get('metrics') or {};trials.append({'source':str(path.relative_to(ROOT)),'outcome':data.get('outcome'),'reason':data.get('reason'),'seconds':seconds,'metrics':metrics,'cursor':(data.get('active_plan') or {}).get('cursor'),'initial_spawn_verified':data.get('initial_spawn_verified'),'objectives_per_minute':metrics.get('high_level_completed',0)*60/seconds if seconds else None})
measured['integrated_trials']=trials
measured['actor_perception_replay']=json.loads((ROOT/'evaluations/v3/actor-perception-benchmark.json').read_text())
measured['stage_completion_claim']=bool(measured['stage_completion_claim'] or any(t['outcome']=='stage_complete' for t in trials))
measured['final_fresh_trial']=next((t for t in trials if args.stage_trial and args.stage_trial in t['source']),None)
measured['tests']=json.loads((ROOT/'evaluations/v3/tests.json').read_text())
measured['legacy_tests']=json.loads((ROOT/'evaluations/unit-report.json').read_text())
measured['v2_tests']=json.loads((ROOT/'evaluations/v2/scenarios.json').read_text())
measured['route_hold_duration_ms']=stats([a['actual_ms'] for a in benchmarks[-1][1].get('continuous_actions',[]) if a['kind']=='move_hold']) if benchmarks else None
measured['comparison_preparation_failures']=[c for c in json.loads((ROOT/'data/v3'/args.combat_cohort/'cases.json').read_text()) if c.get('seconds') is None and not c.get('combat_started')] if args.combat_cohort else []
(ROOT/'evaluations/v3/metrics.json').write_text(json.dumps(measured,indent=2),encoding='utf-8')
raw=baseline['read_only_timings'];probe_rows='\n'.join(rows)
route_rows='\n'.join(f"| {mode} | {v['seconds']['mean']:.3f} | {v['seconds']['p95']:.3f} | {v['reference_pixels_per_minute']['mean']:.2f} | {v['goal_successes']}/{v['attempts']} | {v['move_commands']['mean']:.1f} |" for mode,v in route.items())
speedup=route['v2']['seconds']['mean']/route['continuous']['seconds']['mean'] if 'v2' in route and 'continuous' in route else None
tests=json.loads((ROOT/'evaluations/v3/tests.json').read_text()) if (ROOT/'evaluations/v3/tests.json').exists() else {'groups':{}}
test_count=sum(g['tests'] for g in tests['groups'].values());test_passed=sum(g['passed'] for g in tests['groups'].values())
text=f'''# V3 — aceleração de gameplay

Atualização: {datetime.datetime.now().isoformat(timespec='seconds')}. Trabalho incremental em andamento. Nenhuma conclusão integral de fase é atribuída a estes testes.

## Diagnóstico dos gargalos originais

A V2 já registra zero chamadas ao Qwen no loop tático. O principal gargalo é o ciclo de captura, planejamento local, transição de mapa e comando curto. No trial `5aa90fc7327340cf`,42 movimentos tiveram duração média541,7ms. No trial `99d348c7cb44486e`,31 movimentos tiveram média448,7ms; os três intervalos observacionais entre ataques tiveram média1.927,3ms e máximo/p95 de4.166,3ms. Esses intervalos vêm dos timestamps de observação e não medem exatamente o instante físico de entrada.

Medição atual sem comandos no jogo: oito `shell echo`, média{raw['adb_shell_echo']['mean']:.2f}ms/p95{raw['adb_shell_echo']['p95']:.2f}ms; oito capturas brutas, média{raw['adb_raw_screencap']['mean']:.2f}ms/p95{raw['adb_raw_screencap']['p95']:.2f}ms. Evidência: `evaluations/v3/baseline.json`. A captura por comando e a abertura repetida do mapa são limitações de software. Colisão física com NPC e redução de movimento durante golpe são observações do jogo que exigem plano/controle adequados.

## Mudanças implementadas

Backend persistente `ScrcpyTouch`, servidor oficial3.3.2 com SHA256 verificado contra o instalador da mesma tag; sem root, alteração de arquivos do jogo ou hooks no processo. ADB continua responsável pelo transporte inicial e captura; cada toque posterior usa o socket de controle, com ponteiros distintos. Protocolo e fontes estão em `tools/scrcpy/manifest.json` e `data/v3/research/`. [Fonte oficial](https://github.com/Genymobile/scrcpy/tree/v3.3.2).

`ContinuousActions` oferece `move_hold`, `attack_hold`, `use_skill`, `move_attack_hold` e `execute_sequence`. A duração é explícita, com teto de segurança30s por ação; valores de gameplay devem vir de calibração e geometria. Um timer libera o toque no prazo, mesmo se o observador estiver lento. Um watcher separado trata cancelamento/STOP. `finally` libera os ponteiros; falhas de envio/limpeza são registradas, sem fingir confirmação do Android. Sequências adjacentes compatíveis são agrupadas sem soltar o controle entre microações.

`LiveObserver` captura em paralelo à entrada; o controlador consulta o último estado sem esperar por cada captura. Frames muito antigos ou falhas interrompem a ação. A mesma memória SQLite e o lease de executor V1/V2 são reutilizados. `StageV3Runner` está integrado à fila existente, ao cliente `stage_v3` e ao botão V3 do painel. O progresso de cada objetivo fica na memória persistente e o botão Parar usa o cancelamento existente.

## Benchmarks antes/depois

Primeiras calibrações no mesmo corredor inicial: caminhada1000ms deslocou59,57 pixels de referência; corrida1000ms deslocou74,47. São uma amostra por modo, com retorno ao nascimento confirmado: ganho de deslocamento de aproximadamente25% nesse ensaio, sem extrapolação para toda a fase. Não são metros nem taxa de conclusão de objetivos.

Envio pelo socket: {measured['input_send_ms']}. Erro absoluto da duração mantida nas ações que chegaram ao prazo: {measured['hold_duration_absolute_error_ms']}. São tempos locais de envio/liberação; o protocolo não fornece ACK de cada toque. Deslocamento é confirmado separadamente pelo mapa alinhado.

Benchmark controlado: rota inicial de80 pixels de referência, tolerância de6 pixels, mesma região, retorno observado entre amostras, três repetições por modo. Tempo inclui planejamento, transições e confirmação do endpoint; startup do canal persistente é separado. Ganho V2/contínuo: {speedup} vezes. Evidência: `{str(benchmarks[-1][0].relative_to(ROOT)) if benchmarks else 'pendente'}`.

| Modo | Tempo médio(s) | P95(s) | Progresso(px ref/min) | Objetivos atingidos | Comandos de movimento |
| --- | --- | --- | --- | --- | --- |
{route_rows}

Nove chegadas dentro da tolerância demonstram ganho nessa região; não demonstram navegação universal. A V2 teve intervalos de aproximadamente4,77–5,42s entre seus dois comandos. O modo contínuo usa um comando por caso, portanto não tem amostra de intervalo entre comandos nesse trajeto; o overhead de verificação continua no tempo total. Corrida não demonstrou melhoria no tempo total sobre a caminhada contínua nessa amostra curta. N=3 por modo; p95 nearest rank é o máximo. Cancelamento real, da solicitação ao envio de UP: {measured['cancel_to_up_send_ms']}; liberação recebida pelo Android não tem ACK.

Combates equivalentes são descritos na atualização de medições abaixo. Taxas de colisão em regiões complexas continuam sem amostra suficiente. Ações por chamada ao LLM são não aplicáveis quando o denominador ézero; registrar ações executadas e chamadas separadamente.

## Resultados de navegação

| Execução | Operação | Duração pedida(ms) | Progresso de referência(px) | Mapa confirmou | Retorno ao nascimento | Erro |
| --- | --- | --- | --- | --- | --- | --- |
{probe_rows}

O teste de2s atingiu o NPC no eixo central, limitando o avanço a aproximadamente102px. Agrupar os comandos reduziu transições de toque, mas esse caso não demonstrou aumento de distância: a colisão limita a medição. A aproximação contextual do NPC agora pode interromper a calibração como checkpoint.

## Resultados de combate

`CombatController` implementa estados de detecção, aproximação, engajamento, ataque mantido, orientação após ausência de efeito, habilidade condicionada a disponibilidade observada, recuperação, retirada curta por piso visível e fim de encontro. Cada golpe normal dispensa inferência. Três observações distintas sem inimigo, após presença observada, são exigidas para confirmar apenas o fim do combate visível.

O teste simultâneo de movimento+ataque manteve ponteiros distintos por~1s, mas avançou apenas4,26px. Isso é muito inferior à caminhada isolada e não autoriza assumir que atacar correndo seja eficiente para este personagem. Um ataque mantido isolado durou2501ms com um DOWN/UP e animações observadas; também avançou91,49px. Esse deslocamento é efeito observado durante ataque, não métrica de navegação. O encontro real `v3_prefix_probe_a4e4e2e39c094194` terminou em12,678s de sessão, com4 movimentos e3 períodos de ataque. Três frames sem barras pequenas ou barra focada confirmam apenas o fim do encontro visível. Não é comparação equivalente nem medição de DPS solo: Loraine participa.

No teste integrado, a barra pequena do slime piscou durante um golpe. O checkpoint bruto impediu o falso registro de fim de combate. A percepção agora reconhece a barra focada no topo e procura a borda escura logo abaixo do preenchimento destacado. Contadores do HUD e pixels de caverna permanecem excluídos. Três ausências no vídeo exigem confirmação bruta; se ainda houver inimigo, a FSM volta a observar e combater. Esses casos reais viraram regressões de percepção.

Habilidade disponível, esquiva e retirada ainda não foram validadas no jogo. O starter atual mostra botões de habilidade inativos; não há template de prontidão validado.

## Integração de walkthroughs

Pesquisa e memória V2 preservadas, incluindo guia da Passagem1 e quadros de vídeo observados. `WalkthroughPlanner` compila9 objetivos tipados antes de iniciar: entrada, desvio do NPC, corredor norte, primeiro encontro, ramificação, sala do braseiro, lanternas, encontro final e saída. Cache inclui fase, modo observado, versão do jogo e referência do mapa. Uma tentativa de pesquisa insuficiente fica em cache por24h. O cursor sobrevive a reinício; entrada nova verificada o reinicia. Divergência registra a fonte e a observação sem avançar o objetivo. Os3 primeiros objetivos têm coordenadas locais verificadas; os demais exigem reconhecimento atual de marcos. Fontes externas permanecem reportadas, nunca código executável.

O executor usa segmentos calibrados no piso conhecido e horizonte moderado de observação na exploração. Na fronteira do mapa, só permite extensão curta se a imagem do jogo mostrar piso com margem, sem inimigos nem obstáculos. A aquisição/ignição do braseiro reutiliza os verificadores V2. A abertura e travessia da barreira das lanternas ainda não têm um marco validado; esse objetivo não é declarado concluído pela iluminação isolada. O compilador executável atual é específico da Passagem1 normal; outros modos e fases não recebem uma rota inventada.

## Inferências desnecessárias

Nenhuma chamada ao modelo ocorre nos controladores contínuos. A V2 já tinha esse resultado; a V3 não declara uma redução adicional de chamadas que não ocorreu. O perfil anterior do Qwen é reutilizado: mesmo modelo, pesos e orçamento. Planejamento estratégico e replanejamento de desconhecidos continuam separados das entradas locais.

## Testes, falhas e limitações remanescentes

Testes V3: {test_passed}/{test_count}. Cobrem protocolo, dedos distintos, liberação em exceção/cancelamento/prazo durante captura lenta, guarda da corrida, sequências, FSM de combate, três ausências distintas, recuperação, geometrias com parede e mapa histórico do nascimento. Não são prova de combate real. Resultados e logs: `evaluations/v3/tests.json`.

O jogo apresentou conexão perdida antes de um teste; comandos foram retidos e a reconexão observada devolveu a tela pausada. O backend não tenta contornar telas desconhecidas. Se a conexão com Android cair, envio de UP não equivale a confirmação recebida; o relatório preserva a incerteza.

Pendências prioritárias: concluir comparação de combates equivalentes, validar exploração após o primeiro encontro e o checkpoint da barreira; habilidade disponível, esquiva e retirada ainda exigem ensaios reais adequados. A missão V3 permanece em execução.
'''
text+='''
## Vídeo e custo de observação

O vídeo usa o mesmo servidor scrcpy, H.264 e PyAV19.0.2. O wheel oficial foi verificado por SHA256 e instalado somente no Python em E:. Fonte: [PyAV](https://pyav.org/docs/stable/overview/installation.html). O teste passivo `v3_video_probe_f6446820fc1f420f` recebeu162 frames: intervalo médio49,92ms, p9575,18ms e decodificação média4,12ms. Não enviou entradas. O mapa extraído do vídeo e da imagem bruta deu a mesma posição [944,300]. Isto não mede a latência absoluta Android→host.

O encoder anuncia1600×904. A imagem é normalizada para1600×900, e os toques são convertidos para a geometria anunciada, como exige o protocolo. O primeiro ensaio integrado enviou a geometria errada e não moveu o personagem; o mapa reteve o checkpoint. O erro foi corrigido e tem teste de regressão.

Em10 replays do mesmo frame de combate, visão espacial custou84,39ms e reconhecimento de lanternas117,48ms em média. A observação contínua dispensa essa busca de objetos; os checkpoints brutos continuam fazendo-a. Essa é medição de custo por componente, sem alegar ganho de combate por extrapolação. Frames mantêm sequência, PTS e timestamp de recebimento; imagens antigas param o controle.

## Comparação de combate e integração

Mesmo primeiro encontro, conta, equipe e preparação por rota comum. Tempos incluem a retomada da pausa e observação inicial; startup do backend ocorre ainda pausado. A confirmação final é bruta. A contribuição automática da NPC e o preenchimento inicial das barras são registrados; esta comparação mede o encontro da equipe.

| Modo | Casos medidos | Fins verificados | Média válida(s) | P95 válido(s) |
| --- | --- | --- | --- | --- |
'''
for mode,value in combat_stats.items():
    valid=value['verified_seconds'];average=f"{valid['mean']:.3f}" if valid['n'] else '—';p95=f"{valid['p95']:.3f}" if valid['n'] else '—'
    text+=f"| {mode} | {value['attempts']} | {value['verified_clearances']} | {average} | {p95} |\n"
if not combat_stats:text+='| Pendente | 0 | 0 | — | — |\n'
text+='\nPreparações sem inimigo confirmado e leituras OCR sem identidade suficiente não entram na média de combate. A média válida inclui apenas fins confirmados; retorno com inimigo ainda vivo é falha, nunca tempo de conclusão. Resultados estão separados por série em `combat_cohorts`, com posição e área vermelha iniciais. Dados completos: `evaluations/v3/metrics.json` e `data/v3/v3_combat_benchmark_*/cases.json`.\n\n'
text+='| Trial integrado | Cursor | Ciclos | Chamadas Qwen | Resultado |\n| --- | --- | --- | --- | --- |\n'
for trial in trials:
    if trial['source'].split('\\')[-2] not in ('v3_trial_042e8212b28a46f5',args.stage_trial):continue
    metrics=trial['metrics'] or {};text+=f"| {Path(trial['source']).parent.name} | {trial['cursor']} | {metrics.get('cycles')} | {metrics.get('model_calls')} | {trial['outcome']}: {trial['reason']} |\n"
text+='\nChamadas Qwen/min =0 nos controladores medidos, antes e depois. Ações/LLM = não aplicável com denominador0. Conclusões integrais de fase observadas =0. O ganho comprovado de navegação é restrito à rota comparável de80px; não há alegação de aceleração integral da história.\n'
text+='\n## Latência, decisões e limites da medição\n\n| Modo da rota | Planejamento local médio(ms) | P95(ms) | Planos locais/min | Qwen/min |\n| --- | --- | --- | --- | --- |\n'
for mode,value in route.items():text+=f"| {mode} | {value['planning_ms']['mean']:.2f} | {value['planning_ms']['p95']:.2f} | {value['local_route_plans_per_minute']['mean']:.2f} | {value['qwen_calls_per_minute']['mean']:.1f} |\n"
text+='''
Um plano local corresponde a uma escolha geométrica de rota, não a uma inferência. Há2 planos/movimentos por travessia na V2 e1 no modo contínuo. A taxa por minuto pode aumentar com a velocidade mesmo quando há menos decisões por travessia. As durações históricas de448,7/541,7ms são pedidos ao Android; os tempos locais de DOWN/UP da V3 também não são ACK físico.

Taxa de objetivo atingido na rota =9/9, com tolerância de6px e sem perda de vida observada. Isso não estabelece uma taxa universal de colisão. A colisão com NPC foi observada em2 ensaios específicos de2s e não permite estimar a taxa da história. Não há medição de taxa integral de objetivos ou progresso de fase por minuto; nenhum stage clear foi observado.

Regressões preservadas:45/45 testes legados e59/59 V2. O conjunto V3 inclui protocolos, cancelamento independente, geometrias, decoder real, memória/cursor por entrada, visão de frames reais e hierarquia SQLite integrada. Os resultados sintéticos não contam como conclusão real de fase.

## Ambiente de ensaio e validações restantes

Em2026-11-08 foi conferida a [política operacional oficial](https://guardiantales.com/src/operation.htm), seção4. Após uma suspensão para esclarecer o ambiente, o usuário confirmou explicitamente: Tenho ambiente autorizado. Essa pendência está resolvida; os testes reais foram retomados no ambiente informado. O usuário também determinou continuidade autônoma, sem novas perguntas ou permissões rotineiras.

A primeira série tinha uma medição válida V2 de18,916s; a candidata V3 falhou na preparação por uma detecção transitória. Na retomada, a V2 registrou fim de combate em6,804s, com zero comandos de combate, mas a captura bruta independente ainda mostrou inimigo: falha de conclusão, não ganho de velocidade. As séries atuais e seus resultados estão na tabela e no JSON acima. A navegação confirma inimigos distantes em duas observações distintas; ameaça próxima ou barra focada continua interrompendo imediatamente.

Estado de entrega: implementação incremental, não missão concluída. Permanecem pendentes a comparação completa de combates, a execução integrada após o primeiro encontro, o marco da barreira das lanternas e ensaios de habilidade/esquiva/retirada. Os controladores usam orçamentos limitados, liberam os dedos ao terminar e preservam o estado pausado entre ensaios.
'''
# Remove superseded status paragraphs instead of leaving contradictory claims.
obsolete=('Atualização:','Pendências prioritárias:','Estado de entrega:','A primeira série tinha','Chamadas Qwen/min =0 nos controladores medidos','Taxa de objetivo atingido na rota =9/9','Regressões preservadas:45/45','O executor usa segmentos calibrados')
text='\n'.join(line for line in text.splitlines() if not line.startswith(obsolete))
text+=f'''

## Validação final e correções integradas

Atualização: {datetime.datetime.now().isoformat(timespec='seconds')}. Conclusões reais de saída reconciliadas: {len(reconciliations)}. Em `data/v3/v3_trial_9284f3ddf8044ce2/exit-reconciliation.json`, duas capturas brutas independentes mostram a recompensa de 50 gemas e “Etapa Completada!”. O cursor e as tarefas SQLite foram concluídos com essa prova, sem reenviar interação. O OCR sem espaços e `Observation.frame_path` agora são tratados corretamente. A primeira conclusão teve calibrações, correções e retomadas pelo agente; não representa um ensaio único autônomo desde o nascimento.

O corredor norte real foi atravessado em um hold de 3.471,97ms, com 205,319 pixels de referência, erro final3,84px e tempo total9,361s (`v3_trial_042e8212b28a46f5`). Os trechos agora usam apenas eixos e diagonais45° suportados: o jogo mostrou que vetores rasos podiam mover somente um eixo. Linha de visão e margem são verificadas para cada perna. O horizonte curto permanece para região desconhecida, sem limitar artificialmente corredores conhecidos.

Mapa recém-capturado pode ser reutilizado por até4s se nenhuma entrada ocorreu. Antes de uma interação, a observação de jogo com ator válido por até350ms evita captura redundante. No mapa completo após o primeiro clear, o pin ocultava piso e favorecia uma sala parecida; o alinhamento agora compara candidatos excluindo somente o retângulo observado do ícone e mantém limiar e separação de confiança. O spawn é confirmado pela referência geométrica, não pelo fundo do bounding box de todo o mapa.

`SpatialVision.floor_mask` elimina chamadas completas ao detector de entidades apenas para obter piso. Capacetes são refinados quando necessário e fragmentos reais sustentam a pose durante oclusão pela NPC. Carregamento usa objeto/seta e calibração persistente; quando falta prova, o movimento para. Replay pareado dos mesmos4frames,3repetições por condição (12 por célula), sem entrada no jogo:

| Pipeline | Antes média/p95(ms) | Depois média/p95(ms) |
| --- | --- | --- |
'''
for held,g in measured['actor_perception_replay']['groups'].items():text+=f"| {'Carregando' if held=='True' else 'Sem item'} | {g['before']['mean']:.2f}/{g['before']['p95']:.2f} | {g['after']['mean']:.2f}/{g['after']['p95']:.2f} |\n"
text+='''
Mede somente o componente de visão, excluindo captura, entrada e matcher da pose carregada. Hashes, ordem alternada e casos: `evaluations/v3/actor-perception-benchmark.json`. Não extrapola aceleração integral da fase.

## Puzzle, guia e saída — resultados reais

O fluxo integrado executa luva→pickup→ignição→duas vistas das lanternas→barreira→encontro final→saída, com recuperação do cursor por entrada. A luva removeu os dois tiles; o primeiro reduziu6313pixels verdes para0 e expôs78,6% de piso. O segundo teve10564→16 e74,85% de piso (`c7253326189c4557/tile-reconciliation.json`); a verificação inicialmente escolheu a rocha errada, e a falha original foi preservada ao reconciliar o tile realmente removido.

Ignição: `v3_lantern_probe_186284eed6494f66`, duas observações afastadas526,69pixels de referência da fonte. Luz superior direita: `a06fbb49f6ea4350`; inferior direita final: `63446d2af4c24447`, duas imagens independentes com alvo registrado no mapa. Quatro lanternas ficaram acesas. Em `0b84e4b080de4892`, duas imagens comprovaram painel removido/piso90,5%, e o mapa confirmou travessia para[441,95,812,16], além de toda a borda anterior. O objetivo não depende só da presença de fogo e fica ligado ao token da entrada atual.

O Orc foi observado antes do arremesso e ausente em três capturas posteriores, incluindo uma bruta, sem comando de personagem entre essas confirmações (`v3_trial_7be9bd0f5cb64779/final-encounter-reconciliation.json`). Isso não é uma medição de duração/DPS. Combate com item reconcilia a pose antes da detecção, solta o objeto com prova e usa presença fresca anterior se o inimigo morrer durante a soltura; ainda exige as três ausências e raw independente.

A casa branca no corredor sul exige INTERAÇÃO. O bot observa casa+glyph antes de um único toque e exige duas observações reais de resultado. Estrela preenchida isolada não comprova a partida atual: o caminho alternativo pelo mapa exige entrada, puzzle/encontro, casa e ação emitida; estrela vazia é regressão negativa. O guia em vídeo P8Kob7UhlNs foi observado na saída1:55 e retorno ao mapa1:58. Guias ficam como relato e checkpoints atuais decidem a execução. O compilador permanece específico de Passagem1 normal; outras fases/modos não recebem rota inventada.

## Métricas de aceitação e limites

Chamadas Qwen/min =0 antes e depois nos loops medidos. Ações/LLM =N/A com denominador0, sem alegar redução adicional. Objetivos da rota =9/9; falhas de chegada =0/9 (erro<=6px), sem perda de vida observada. Isso é proxy definido, não medição física universal de colisões. A colisão com NPC limitou dois ensaios específicos de2s; em regiões complexas, falhas/recusas ficam preservadas nos reports.
'''
final=measured['final_fresh_trial']
if final:text+=f"\nEnsaio integrado final `{final['source']}`: resultado `{final['outcome']}`, cursor {final['cursor']}/9, nascimento verificado {final['initial_spawn_verified']}, {final['metrics'].get('high_level_completed',0)} objetivos em {final['seconds']:.3f}s, {final['objectives_per_minute']:.3f} objetivos/min; {final['metrics'].get('cycles',0)} ciclos. Motivo: {final['reason'] or '—'}.\n"
else:text+='\nO ensaio integral final desde o nascimento ainda não está registrado. Não há comparação integral V2/V3 de tempo da fase.\n'
text+=f"\nComparação de combate selecionada: `{args.combat_cohort or 'histórico, sem série final selecionada'}`. Não misturar séries antigas com código diferente. Tempos de falha não contam como conclusão. Os JSONs preservam entradas iniciais, raw final, ações e erros.\n"
text+=f"\nComparação temporal estrita usa somente repetições com ambos os controladores concluídos: {paired_repetitions}. V2: {measured['paired_combat_seconds']['v2']}; V3: {measured['paired_combat_seconds']['v3_video']} (segundos). A terceira V2 sem conclusão não recebe tempo fictício e não forma par temporal. Diferença V3−V2 por par: {measured['paired_combat_v3_minus_v2_seconds']}. Amostra pequena com contribuição da NPC; não demonstra ganho geral de combate.\n"
for case in combat_cases:
    if case.get('error'):text+=f"\nFalha de combate {case['mode']}, repetição{case['repetition']}: {case['error']}. Tempo até falha: {case.get('seconds','indisponível')}; {case.get('timing_unavailable_reason','sem atribuição de tempo de conclusão')}.\n"
text+='\nTaxa integral de conclusão não é extrapolada de uma fase. Habilidade pronta, esquiva e retirada ainda carecem de ensaio real apropriado; starter tem botões inativos. Nenhum novo modelo, agente ou framework foi introduzido. Preservados hierarquia, SQLite, lease, STOP e fila V1/V2. Telas desconhecidas ou perda de conexão interrompem o executor; não há compra, root ou hook.\n'
v2groups=measured['v2_tests']['groups'];legacy=measured['legacy_tests']
text+=f"\nVerificação final: V3 {test_passed}/{test_count}; legado {legacy['passed']}/{legacy['tests_run']}; V2 {sum(g['passed'] for g in v2groups.values())}/{sum(g['tests'] for g in v2groups.values())}. JSONs e logs guardam falhas completas; fixtures não provam gameplay novo.\n"
text+=f"\nDuração real dos holds de movimento no ensaio de rota, incluindo retornos entre amostras: {measured['route_hold_duration_ms']} (ms). Preparações da série final sem tempo de combate medido: {len(measured['comparison_preparation_failures'])}; não entram na média de conclusão. Falha de ação é reportada pelo endpoint fora da tolerância ou combate sem prova bruta, não por cada interrupção preventiva de segurança.\n"
(ROOT/'docs/V3_GAMEPLAY_ACCELERATION.md').write_text(text,encoding='utf-8')
print(json.dumps({'report':str(ROOT/'docs/V3_GAMEPLAY_ACCELERATION.md'),'probes':len(probes),'send_ms':measured['input_send_ms']},ensure_ascii=False))
