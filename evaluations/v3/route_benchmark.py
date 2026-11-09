"""Matched 80-reference-pixel safe route: V2 versus continuous walk/run."""
from pathlib import Path
import argparse,json,math,statistics,sys,time,urllib.request
import cv2
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from bot import ADB
from cognitive.contracts import uid,Provenance
from cognitive.fast_control import FastSession
from cognitive.memory import Memory
from cognitive.map_anchor import SpawnMapAnchor
from cognitive.map_navigation import PauseMap
from cognitive.stage_v2 import InteractionVision
from cognitive.v3.input_backend import ScrcpyTouch
from cognitive.v3.continuous import ContinuousActions
from cognitive.v3.observation import LiveObserver
from cognitive.v3.segments import SegmentPlanner

class TimedADB(ADB):
    def __init__(self):super().__init__();self.movements=[]
    def hold(self,x,y,ms,w,h):
        is_joystick=math.dist((x*w,y*h),(.1475*w,.737*h))<140;start=time.perf_counter()
        try:return super().hold(x,y,ms,w,h)
        finally:
            if is_joystick:self.movements.append({'start':start,'end':time.perf_counter(),'requested_ms':ms})

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repeats',type=int,default=3);args=parser.parse_args()
    if not 1<=args.repeats<=5:raise SystemExit('Use 1..5 controlled repetitions')
    try:urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=1)
    except Exception:pass
    else:raise SystemExit('Stop main worker before benchmark')
    memory=Memory(ROOT/'data/cognitive.sqlite');adb=TimedADB();session=FastSession(ROOT,adb,memory,run_id=uid('v3_route_benchmark'),artifact_base='data/v3');session.kind='v3_matched_route_benchmark_not_stage_completion'
    backend=ScrcpyTouch(ROOT,adb,session.folder);controls=None;cases=[];error=None;cleanup=None
    try:
        reference=memory.retrieve(session.scope,kind='v2_spawn_anchor',include_global=False,limit=1)[0];anchor=SpawnMapAnchor.load(reference['content'],ROOT);session.map_anchor=anchor
        profiles=json.loads((ROOT/'evaluations/v3/input-profile.json').read_text());speeds={mode:statistics.median(p['reference_pixels_per_ms'] for p in profiles if p['mode']==mode and p['anchor_id']==anchor.identity) for mode in ('move','run')}
        neutral=cv2.imread(str(ROOT/'data/v2/v2_calibration_45124c972be4410b/0048-after-jogo.jpg'));vision=InteractionVision(ROOT)
        backend.connect();controls=ContinuousActions(backend,json.loads((ROOT/'config.json').read_text())['controls'],session.cancel,[ROOT/'data/v3/STOP',ROOT/'data/v2/STOP'],lambda:float(cv2.matchTemplate(InteractionVision.mask(session.last_frame),InteractionVision.mask(neutral),cv2.TM_CCOEFF_NORMED)[0,0])>.92)
        def state(label):
            frame,f=session.capture(label);s=PauseMap().parse(frame);a=anchor.locate(s)
            if not a:raise RuntimeError('Benchmark map reference unavailable')
            s.update(map_scale=a['scale'],anchor_alignment=a);return s,a,anchor.project(s['player'],a),f
        def raw(point,a):return [(point[i]-a['source_origin'][i])*a['scale']+a['top_left'][i] for i in range(2)]
        def policy(snap,returning=False):
            f=snap['features']
            if f['scene']!='jogo':return 'screen_changed'
            if f['health'] is not None and f['health']<.8:return 'unexpected_health_drop'
            if f['enemy_count'] or f['hazard_count']:return 'unexpected_threat'
            if not returning and vision.affordance(snap['frame']):return 'npc_checkpoint'
        def observed_sequence(sequence,returning=False):
            observer=LiveObserver(session).start()
            try:return controls.execute_sequence(sequence,monitor=lambda:observer.reason(lambda snap:policy(snap,returning)))
            finally:observer.close()
        for repetition in range(args.repeats):
            for mode in ('v2','continuous','run'):
                session.check_cancel();session.transition('pausa');s,a,start_ref,initial=state('benchmark-start-map')
                if not anchor.is_spawn(s):raise RuntimeError('Benchmark repetition must start at the verified initial stem')
                target=[start_ref[0],start_ref[1]-80];start_frame=initial['frame'];frame_index=session.frames;move_index=len(adb.movements);action_index=len(controls.actions);decision_ms=[];outcomes=[]
                started=time.perf_counter()
                if mode=='v2':
                    for step in range(8):
                        current=anchor.project(s['player'],a)
                        if math.dist(current,target)<=6:break
                        row=session.navigate_once(raw(target,a),allow_combat=False,allow_interaction=False);decision_ms.append(row['planning_ms']);outcomes.append({'verified':row['metrics']['verified']})
                        s=PauseMap().parse(session.last_frame);a=anchor.locate(s)
                        if not a:raise RuntimeError('V2 endpoint map alignment lost')
                        s.update(map_scale=a['scale'],anchor_alignment=a)
                else:
                    planning=time.perf_counter();plan=SegmentPlanner(speeds['run' if mode=='run' else 'move']).plan(s,raw(target,a));decision_ms.append((time.perf_counter()-planning)*1000)
                    session.transition('jogo');frame,f=session.capture('before-segment')
                    if f['enemy_count'] or f['hazard_count'] or not f['player'] or f['health']<.8:raise RuntimeError('Continuous benchmark preconditions changed')
                    sequence=[{'op':'move_hold','direction':seg['direction'],'duration_ms':seg['duration_ms'],'run':mode=='run'} for seg in plan['segments']]
                    outcomes=observed_sequence(sequence);session.transition('pausa');s=PauseMap().parse(session.last_frame);a=anchor.locate(s)
                    if not a:raise RuntimeError('Continuous endpoint map alignment lost')
                end_ref=anchor.project(s['player'],a);elapsed=time.perf_counter()-started;distance=start_ref[1]-end_ref[1];goal_error=math.dist(end_ref,target);moves=adb.movements[move_index:];actions=controls.actions[action_index:]
                gaps=[(b['start']-a['end'])*1000 for a,b in zip(moves,moves[1:])] if mode=='v2' else [(b['start_monotonic']-a['end_monotonic'])*1000 for a,b in zip(actions,actions[1:])]
                case={'repetition':repetition,'mode':mode,'requested_reference_distance':80,'actual_reference_distance':distance,'goal_error_reference_pixels':goal_error,'goal_success':goal_error<=6 and session.last_features['health']>=initial['health']-.03,'seconds':elapsed,'reference_pixels_per_minute':distance/elapsed*60,'move_commands':len(moves) if mode=='v2' else len(actions),'command_idle_gaps_ms':gaps,'planning_ms':decision_ms,'captures':session.frames-frame_index,'qwen_calls':0,'before':start_ref,'after':end_ref,'before_frame':start_frame,'after_frame':session.last_features['frame'],'outcomes':outcomes}
                cases.append(case);(session.folder/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:case[k] for k in ('repetition','mode','seconds','actual_reference_distance','goal_error_reference_pixels','goal_success','move_commands')}),flush=True)
                memory.remember('episodic','v3_route_benchmark',session.scope,{'run_id':session.run_id,**case},Provenance(case['after_frame'],method='matched_route_with_identical_goal_tolerance'),.95,'verified' if case['goal_success'] else 'uncertain')
                if not case['goal_success']:raise RuntimeError('Matched goal not reached; stop benchmark rather than counting a speedup')
                # Return is outside the measured route interval and has its own checkpoint.
                session.transition('jogo');session.capture('before-reset');observed_sequence([{'op':'move_hold','direction':'down','duration_ms':distance/speeds['move']}],returning=True);session.transition('pausa');returned,_,_,_=state('benchmark-reset-map')
                if not anchor.is_spawn(returned):raise RuntimeError('Benchmark return did not restore the start region')
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    finally:
        if controls:
            try:controls.close()
            except Exception as exc:error=(error or '')+'; close: '+str(exc)
        cleanup=backend.close()
        try:session.transition('pausa')
        except Exception as exc:error=(error or '')+'; pause: '+str(exc)
        report=session.close();report.update(cases=cases,error=error,backend=cleanup,continuous_actions=controls.actions if controls else [],stage_complete=False);(session.folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');memory.close();print(json.dumps({'folder':str(session.folder),'cases':len(cases),'error':error},ensure_ascii=False),flush=True)
