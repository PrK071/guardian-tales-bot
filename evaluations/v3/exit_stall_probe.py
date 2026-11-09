"""Reproduce one recorded exit-wall stall with current-entry/map guards."""
from pathlib import Path
import argparse,json,sys,hashlib,urllib.request
import cv2
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from bot import ADB
from cognitive.contracts import uid
from cognitive.memory import Memory
from cognitive.v3.session import GameplaySession
from cognitive.v3.exit_control import recenter_exit_after_stall,verified_exit_context

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);args=parser.parse_args()
    try:urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=1)
    except Exception:pass
    else:raise RuntimeError('Stop the main worker before the isolated probe')
    source=(ROOT/'data/v3'/args.source).resolve()
    if source.parent!=(ROOT/'data/v3').resolve():raise RuntimeError('Source outside trial data')
    prior=json.loads((source/'report.json').read_text())
    if 'Exit forward segment did not progress in the independent map' not in prior.get('reason',''):raise RuntimeError('Source lacks an independently confirmed exit stall')
    memory=Memory(ROOT/'data/cognitive.sqlite');session=None;result=None;error=None;before_evidence=None
    try:
        active=memory.retrieve('world:1:passage:1',kind='v3_active_plan',include_global=False,limit=1)[0]['content']
        if active.get('entry_token')!=prior['active_plan'].get('entry_token') or active.get('cursor')!=8:raise RuntimeError('Recorded stall belongs to another stage entry')
        adb=ADB();adb.connect();session=GameplaySession(ROOT,adb,memory,run_id=uid('v3_exit_stall_probe'))
        _,_,position,map_features=session.map_state('v3-exit-stall-probe-map');verified_exit_context(session,position,map_features['frame'])
        stalls=[r['content'] for r in memory.retrieve(session.scope,kind='v3_exit_stall',include_global=False,limit=8) if r['content'].get('run_id')==args.source]
        if not stalls or any(abs(position[i]-stalls[0]['check']['after'][i])>3 for i in (0,1)):raise RuntimeError('Current pose differs from recorded stall')
        session.transition('jogo');frame,features=session.capture('v3-exit-stall-probe-before');path=session.folder/'controller-input.png';cv2.imwrite(str(path),frame)
        before_evidence={'path':str(path.relative_to(ROOT)),'pixels_bgr_sha256':hashlib.sha256(frame.tobytes()).hexdigest(),'features':features,'position_reference':position}
        result=recenter_exit_after_stall(session,position)
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    finally:
        if session:
            try:session.transition('pausa')
            except Exception as exc:error=error or 'pause: '+str(exc)
            report=session.close();report.update(source_trial=args.source,result=result,error=error,before_evidence=before_evidence,stage_complete=False)
            (session.folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'folder':str(session.folder),'result':result,'error':error},ensure_ascii=False))
        memory.close()
    return 0 if result and result['verified'] and not error else 1

if __name__=='__main__':raise SystemExit(main())
