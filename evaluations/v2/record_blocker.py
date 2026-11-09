"""Reconcile the pre-input worker failure with the persisted V2 goal only."""
from pathlib import Path
import json,sys,time,urllib.request
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from cognitive.memory import Memory
from cognitive.contracts import Provenance,State
device=json.loads((ROOT/'evaluations/v2/device-status.json').read_text(encoding='utf-8'))
if time.time()-device['at']>300:raise SystemExit('Refusing stale device evidence; run check_device.py first.')
try:urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=1)
except Exception:pass
else:raise SystemExit('Stop the main worker before reconciling this offline failure.')
memory=Memory(ROOT/'data/cognitive.sqlite');updated=[]
if not device['ok']:
    for goal in memory.goals():
        if goal['title']!='V2: complete Kanterbury Forest Passage 1 with real evidence' or goal['state']==State.COMPLETED:continue
        memory.goal_state(goal['id'],State.BLOCKED)
        for task in memory.tasks(goal['id']):
            if task.state!=State.COMPLETED:task.state=State.BLOCKED;task.data['reason']='ADB unavailable before initial stage observation';memory.save_task(task)
        memory.remember('working','blocker','world:1:passage:1',{'goal_id':goal['id'],'device_evidence':'evaluations/v2/device-status.json','reason':'ADB unavailable; initial observation failed; no stage input sent','stage_completed':False},Provenance('evaluations/v2/device-status.json'),.99,'verified',dedupe='v2-device-blocker:'+goal['id'])
        updated.append(goal['id'])
integrity=memory.db.execute('PRAGMA quick_check').fetchone()[0]
memory.close();result={'updated_v2_goals':updated,'sqlite_quick_check':integrity,'real_stage_completed':False}
(ROOT/'evaluations/v2/memory-consistency.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
