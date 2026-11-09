"""Consolidate closed-run measurements without promoting calibration to clear."""
from pathlib import Path
import datetime,json
ROOT=Path(__file__).resolve().parents[2]
m=json.loads((ROOT/'evaluations/v2/metrics.json').read_text(encoding='utf-8'))
t=json.loads((ROOT/'evaluations/v2/scenarios.json').read_text(encoding='utf-8'))
v1=json.loads((ROOT/'evaluations/unit-report.json').read_text(encoding='utf-8'))
live=m['live_stage_metrics'];q=m['model_profile']['by_context']
groups=t['groups'];tests=sum(g['tests'] for g in groups.values());passed=sum(g['passed'] for g in groups.values())
rows='\n'.join('| '+ ' | '.join((Path(r['report']).parent.name,r['kind'],str(r['outcome']),str(r['seconds']),r.get('reason') or '—'))+' |' for r in m['trial_results'])
test_rows='\n'.join(f"| {kind} | {g['passed']}/{g['tests']} |" for kind,g in groups.items())
qrows='\n'.join(f"| {name} | {v['mean_input_tokens']} | {v['mean_inference_ms']/1000:.3f} | {v['p95_inference_ms']/1000:.3f} | {v['grounded']}/{v['samples']} |" for name,v in q.items())
calibrations='\n'.join(f"- `{r['report']}`: fase `{r.get('phase')}`, {r['seconds']} s, {r['actions']} ações; resultado `{json.dumps(r.get('result'),ensure_ascii=False)}`; erro `{r.get('error')}`." for r in m.get('lantern_calibrations',[]))
text=f'''# Guardian Tales Autonomous Agent V2 — evidências e execução

Atualizado em {datetime.datetime.now().isoformat(timespec='seconds')}. Base: relatórios encerrados; execuções abertas não entram nas taxas.

## 1. Resumo executivo

**O marco principal permanece pendente: nenhuma fase real foi concluída do nascimento à confirmação de resultado.** Alvo observado: Mundo 1, 1-1 Floresta Kanterbury Passagem 1, Normal; objetivo de entrada: “Derrote monstros.” O agente demonstrou navegação e combate local, mas parou diante do puzzle de lanternas. O desenvolvimento continua incrementalmente em `E:\\GuardianTalesBot`, preservando V1 em `backups/before-v2/`.

Foram encerradas {m['stage_trials']} tentativas V2, sendo {m['initial_to_finish_trials']} iniciadas no nascimento e {m['stage_trials']-m['initial_to_finish_trials']} retomadas. A taxa de conclusão desde o início é {m['initial_to_finish_completed']}/{m['initial_to_finish_trials']}. Calibrações, preparação de menus e testes simulados são contabilizados separadamente.

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

V1: consultar `evaluations/unit-report.json`, última regressão conhecida 45/45. V2 consolidado: **{passed}/{tests}**. Grupos históricos são imagens reais reprocessadas; grupos simulados não executam comandos na conta.

| Grupo | Passaram/total |
| --- | --- |
{test_rows}

Os dez cenários obrigatórios cobrem navegação, bloqueio, interação com/sem efeito, combate, hipótese recuperada, replanejamento, retomada, pesquisa sem resultado e falso positivo de conclusão. SQLite temporário dos testes não recebe status de conclusão na memória da conta.

Reproduzir: Python do projeto com `evaluations/run_tests.py`, `evaluations/v2/test_scenarios.py` e, para métricas/documentação, `evaluations/v2/summarize.py` seguido de `evaluations/v2/write_report.py`. Não é necessário repetir o profiling do modelo para essas verificações.

## 6. Métricas de desempenho

Tentativas encerradas: {live['seconds']:.3f} s, {live['actions']} ações. Ciclo completo: média {live['navigation_cycle_ms']['mean']} ms, p95 {live['navigation_cycle_ms']['p95']} ms. Planejamento local isolado, nas versões que o separaram: média {live['isolated_local_planning_ms']['mean']} ms, p95 {live['isolated_local_planning_ms']['p95']} ms. Não misturar o antigo `decision_ms`, que media o ciclo inteiro, com a latência isolada.

Controlador: média {live['controller_ms']['mean']} ms, p95 {live['controller_ms']['p95']} ms. Foram confirmados {live['map_confirmed_moves']} movimentos com extensão estável e {live['aligned_map_confirmed_moves']} com alinhamento; os conjuntos podem sobrepor-se. Progresso alinhado: {live['aligned_map_reference_pixels_per_minute']:.3f} pixels de referência/minuto; não é distância física nem percentual da fase.

Contadores registrados: {live['recorded_navigation_failures']} falhas de navegação, {live['successful_recoveries']} recuperações e {live['interruptions_without_recovery']} interrupções sem recuperação na respectiva tentativa. Alguns erros antigos não foram classificados por esses contadores: os motivos textuais de cada relatório são a evidência causal. {live['model_calls']} chamadas ao modelo, {live['input_tokens']} tokens de entrada e {live['output_tokens']} de saída no loop determinístico. P95 usa nearest rank.

As nove calibrações anteriores somam {m['calibration_seconds']} s, {m['calibration_actions']} ações e {m['move_actions']} movimentos, com {m['map_confirmed_moves']} confirmações de mapa estável. As calibrações de lanternas abaixo são separadas.

## 7. Avaliação do Qwen3-0.6B

Mesmo Qwen3-0.6B Q8, duas threads, orçamento de saída de 160 tokens, nove inferências reais. Pesos e configurações preservados; modelo não substituído.

| Contexto | Tokens de entrada | Média (s) | P95 (s) | Respostas fundamentadas |
| --- | --- | --- | --- | --- |
{qrows}

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

{calibrations or 'Nenhuma calibração de lanternas encerrada.'}

## 9. Resultados de conclusão de fase

**{m['initial_to_finish_completed']} conclusões comprovadas desde o início.** Nenhuma rota completa reproduzível. O critério exige duas observações independentes de resultado reconhecido, fase correta e ausência de tela bloqueada; chegar a uma fronteira ou eliminar inimigos visíveis não basta.

| Execução | Tipo | Resultado | Segundos | Motivo |
| --- | --- | --- | --- | --- |
{rows}

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
'''
(ROOT/'docs/V2_END_TO_END_REPORT.md').write_text(text,encoding='utf-8')
print(json.dumps({'report':str(ROOT/'docs/V2_END_TO_END_REPORT.md'),'v2_tests':f'{passed}/{tests}','stage_completed':m['initial_to_finish_completed']},ensure_ascii=False))
