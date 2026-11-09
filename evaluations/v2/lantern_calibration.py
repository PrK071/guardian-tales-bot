"""Bounded real pickup calibration. Main game worker must be stopped."""
from pathlib import Path
import argparse,json,sys,urllib.request
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from bot import ADB
from cognitive.contracts import uid
from cognitive.memory import Memory
from cognitive.fast_control import FastSession
from cognitive.map_anchor import SpawnMapAnchor
from cognitive.lantern_control import LanternController
from cognitive.map_navigation import PauseMap
from cognitive.stage_v2 import StageRunner

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['arrive','approach','pickup','ignite'],default='approach');args=parser.parse_args()
    try:urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=1)
    except Exception:pass
    else:raise SystemExit('Main server must be explicitly stopped before calibration')
    memory=Memory(ROOT/'data/cognitive.sqlite');session=FastSession(ROOT,ADB(),memory,run_id=uid('v2_lantern_calibration'))
    session.kind='lantern_calibration_not_stage_completion';error=None;result=None
    try:
        reference=memory.retrieve(session.scope,kind='v2_spawn_anchor',include_global=False,limit=1)[0]
        session.map_anchor=SpawnMapAnchor.load(reference['content'],ROOT);session.capture('initial')
        runner=StageRunner(SimpleNamespace(),SimpleNamespace(memory=memory),ROOT)
        session.interaction_handler=runner.interact
        if args.phase=='arrive':runner.configure_map_reference(session,PauseMap().parse(session.last_frame),session.scope)
        controller=LanternController(session,seconds=900 if args.phase=='arrive' else 180)
        if args.phase=='arrive':
            for step in range(100):
                controller.check()
                # navigate_once already records gameplay before/after movement.
                # Inspect that current observation without a second UI cycle.
                features=session.world_features
                if features and controller.objects(features,'portable_brazier'):
                    result={'object_visible':True,'frame':features['frame'],'step':step};break
                move=session.navigate_once()
                print(json.dumps({'step':step,'kind':move['kind'],'verified':move.get('metrics',{}).get('verified')}),flush=True)
            else:raise RuntimeError('Room arrival budget exhausted')
        elif args.phase=='pickup':result=controller.pickup()
        elif args.phase=='ignite':result=controller.ignite()
        else:
            _,f,obj=controller.approach('portable_brazier');result={'object':obj,'player':f['player'],'frame':f['frame']}
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    finally:
        try:session.transition('pausa')
        except Exception as exc:error=(error or '')+'; pause: '+str(exc)
        report=session.close();report.update(phase=args.phase,result=result,error=error,stage_complete=False)
        (session.folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');memory.close()
        print(json.dumps({'folder':str(session.folder),'result':result,'error':error,'seconds':report['seconds']},ensure_ascii=False),flush=True)
