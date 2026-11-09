"""Compare full-axis touch with ramped swipe on the observed safe spawn stem."""
from pathlib import Path
import json,sys,urllib.request
import cv2
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from bot import ADB
from cognitive.contracts import Action,uid
from cognitive.fast_control import FastSession
from cognitive.memory import Memory
from cognitive.map_anchor import SpawnMapAnchor
from cognitive.map_navigation import PauseMap
try:urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=1)
except Exception:pass
else:raise SystemExit('Stop main worker first')
memory=Memory(ROOT/'data/cognitive.sqlite');session=FastSession(ROOT,ADB(),memory,run_id=uid('v2_joystick_calibration'));session.kind='joystick_calibration_not_stage_completion';result=None;error=None
try:
    reference=memory.retrieve(session.scope,kind='v2_spawn_anchor',include_global=False,limit=1)[0];anchor=SpawnMapAnchor.load(reference['content'],ROOT)
    frame,_=session.capture('initial');before=PauseMap().parse(frame)
    if not anchor.is_spawn(before):raise RuntimeError('Calibration requires the known safe initial stem')
    session.transition('jogo');_,f=session.capture('safe-stem')
    if f['enemy_count'] or f['hazard_count']:raise RuntimeError('Unexpected threat in joystick calibration')
    session.joystick_style='fixed_hold';session.pulse(Action('move',{'direction':'up','ms':900},'Measure fixed-axis joystick input on the safe spawn stem'))
    session.transition('pausa');frame,_=session.capture('result-map');after=PauseMap().parse(frame)
    result=anchor.motion(before,after,'up')
except Exception as exc:error=str(exc)
finally:
    try:session.transition('pausa')
    except Exception as exc:error=(error or '')+'; pause: '+str(exc)
    report=session.close();report.update(result=result,error=error,stage_complete=False);(session.folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');memory.close()
    print(json.dumps({'folder':str(session.folder),'result':result,'error':error},ensure_ascii=False),flush=True)
