"""V2 closed-run baseline plus read-only ADB/capture timing; no game input."""
from pathlib import Path
import json,math,statistics,sys,time
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from bot import ADB
def stats(values):
    v=sorted(values);return {'n':len(v),'mean':statistics.mean(v) if v else None,'p95':v[math.ceil(.95*len(v))-1] if v else None}
reports=[]
for path in (ROOT/'data/v2').glob('v2_*/report.json'):
    r=json.loads(path.read_text(encoding='utf-8'))
    if r.get('kind') in ('initial_stage_trial','resumed_stage_trial','lantern_calibration_not_stage_completion'):reports.append((path,r))
rows=[]
for path,r in reports:
    actions=r.get('actions',[]);moves=[a for a in actions if a['action']['op']=='move'];attacks=[a for a in actions if a['action']['op']=='attack']
    # before/after stamps bound observation gaps; not exact physical input times.
    gaps=[max(0,(b['before']['at']-a['after']['at'])*1000) for a,b in zip(actions,actions[1:])]
    attack_gaps=[max(0,(b['before']['at']-a['after']['at'])*1000) for a,b in zip(attacks,attacks[1:])]
    rows.append({'report':str(path.relative_to(ROOT)),'kind':r['kind'],'seconds':r['seconds'],'actions':len(actions),'moves':len(moves),'move_duration_ms':stats([a['action']['args']['ms'] for a in moves]),'attack_duration_ms':stats([a['action']['args']['ms'] for a in attacks]),'observation_gaps_ms':stats(gaps),'attack_observation_gaps_ms':stats(attack_gaps),'raw_capture_ms':stats([a['before']['capture_ms'] for a in actions]),'controller_ms':stats([a['metrics']['controller_ms'] for a in actions]),'cycles':r.get('metrics',{}).get('cycles'),'model_calls':r.get('metrics',{}).get('model_calls',0),'outcome':r.get('outcome',r.get('error'))})
adb=ADB();timings={}
for label,args,n in [('adb_shell_echo',('shell','echo','v3-latency'),8),('adb_raw_screencap',('exec-out','screencap'),8)]:
    samples=[]
    for _ in range(n):
        start=time.perf_counter();raw=adb.call(*args);samples.append((time.perf_counter()-start)*1000)
        if label=='adb_raw_screencap' and len(raw)!=5760016:raise RuntimeError('Unexpected raw capture layout')
    timings[label]=stats(samples)
result={'at':time.time(),'historical_runs':rows,'read_only_timings':timings,'llm_finding':'V2 tactical loop already records zero Qwen calls. The V3 bottleneck is per-action UI/capture/ADB orchestration, not one LLM call per hit.','limitations':['Historical gaps are observation-stamp estimates, not exact input issue/finish measurements.','Different route portions, health and code revisions cannot prove equivalent combat or route speedup.']}
(ROOT/'evaluations/v3/baseline.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'runs':len(rows),'timings':timings,'model_calls_v2':0},ensure_ascii=False))
