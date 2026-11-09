"""Validate a recorded NPC bypass, long corridor and first real encounter."""
from pathlib import Path
import json,sys,time,urllib.request,math
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from bot import ADB
from cognitive.contracts import Task,State,uid
from cognitive.memory import Memory
from cognitive.v3.session import GameplaySession

try:urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=1)
except Exception:pass
else:raise SystemExit('Stop main worker before standalone encounter validation')
source=ROOT/'data/v2/v2_lantern_calibration_cface23508d84a6d/navigation.jsonl';rows=[json.loads(line) for line in source.read_text(encoding='utf-8').splitlines()]
indices=[0,1,6,7]
if not all(rows[i]['verified'] and rows[i].get('aligned_map_motion',{}).get('verified') for i in indices):raise SystemExit('Recorded route hints are not verified')
targets=[rows[i]['aligned_map_motion']['after'] for i in indices]
memory=Memory(ROOT/'data/cognitive.sqlite');session=GameplaySession(ROOT,ADB(),memory,run_id=uid('v3_prefix_probe'));session.kind='v3_prefix_calibration_not_stage_completion'
goal_id=memory.goal('V3 calibration: recorded corridor and continuous first encounter');task=Task(uid('v3_calibration_task'),goal_id,'v3_calibration','Validate the initial corridor and one visible encounter',session.scope,success={'visible_combat_ended':True},max_attempts=12,state=State.RUNNING);memory.save_task(task);memory.goal_state(goal_id,State.RUNNING);session.goal_id=goal_id;session.task_id=task.id
error=None;result=None;segments=[];resumed_at=0
try:
    state,_,point,_=session.map_state('probe-initial-map')
    if not session.map_anchor.is_spawn(state):
        matches=[i for i,target in enumerate(targets) if math.dist(point,target)<=7]
        if not matches:
            session.transition('jogo');_,f=session.capture('probe-resume-encounter-check')
            if not f['enemy_count']:raise RuntimeError('No matched recorded checkpoint or currently observed encounter to resume')
            resumed_at=len(targets);result=session.fight_continuously(45)
        else:resumed_at=max(matches)+1
    for target in ([] if result else targets[resumed_at:]):
        for attempt in range(3):
            row=session.navigate_to(target,tolerance=7,allow_npc_bypass=True);segments.append(row)
            print(json.dumps({'target':target,'verified':row['verified'],'reason':row.get('reason'),'seconds':row.get('seconds'),'control_ms':[a['requested_ms'] for a in row.get('controls',[])]}),flush=True)
            if row.get('reason')=='enemy_detected':result=session.fight_continuously(45);break
            if row['verified']:break
            if row.get('reason') not in ('duration_elapsed','npc_checkpoint'):raise RuntimeError('Route interrupted: '+str(row.get('reason')))
        else:raise RuntimeError('Recorded corridor checkpoint not reached after three replans')
        if result:break
    if not result:
        session.transition('jogo')
        for _ in range(5):
            _,f=session.capture('encounter-trigger-observe')
            if f['enemy_count']:result=session.fight_continuously(45);break
            time.sleep(.10)
    if not result:raise RuntimeError('Expected encounter not observed; guide checkpoint requires investigation')
    if result['visible_combat_ended']:task.state=State.COMPLETED;memory.goal_state(goal_id,State.COMPLETED)
    else:task.state=State.BLOCKED;memory.goal_state(goal_id,State.BLOCKED)
except Exception as exc:error=type(exc).__name__+': '+str(exc);task.state=State.INTERRUPTED if isinstance(exc,InterruptedError) else State.BLOCKED;memory.goal_state(goal_id,task.state)
finally:
    memory.save_task(task)
    try:session.transition('pausa')
    except Exception as exc:error=(error or '')+'; pause: '+str(exc)
    report=session.close();report.update(source_route=str(source),targets=targets,resumed_at=resumed_at,result=result,error=error,stage_complete=False);(session.folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');memory.close()
    print(json.dumps({'folder':str(session.folder),'error':error,'combat_outcome':result['outcome'] if result else None,'visible_combat_ended':result['visible_combat_ended'] if result else False},ensure_ascii=False),flush=True)
