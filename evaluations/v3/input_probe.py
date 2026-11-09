"""Real bounded continuous-input calibration, sharing the existing game lease."""
from pathlib import Path
import argparse,json,sys,threading,time,urllib.request
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

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('op',choices=['connect','move','run','attack','combined','sequence','interrupt','restore']);parser.add_argument('--ms',type=int,default=1000);parser.add_argument('--direction',default='up');parser.add_argument('--roundtrip',action='store_true');args=parser.parse_args()
    try:urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=1)
    except Exception:pass
    else:raise SystemExit('Stop main worker before standalone input calibration')
    memory=Memory(ROOT/'data/cognitive.sqlite');session=FastSession(ROOT,ADB(),memory,run_id=uid('v3_input_probe'),artifact_base='data/v3');session.kind='v3_input_calibration_not_stage_completion'
    backend=ScrcpyTouch(ROOT,session.adb,session.folder);controller=None;result=None;error=None;backend_result=None;before_map=None;cancel_at=None;observations=[]
    try:
        session.capture('initial');before_map=PauseMap().parse(session.last_frame)
        reference=memory.retrieve(session.scope,kind='v2_spawn_anchor',include_global=False,limit=1)[0];anchor=SpawnMapAnchor.load(reference['content'],ROOT)
        if args.op not in ('connect','restore') and not anchor.is_spawn(before_map):raise RuntimeError('Input calibration requires safe initial spawn; prepare stage first')
        if args.op=='restore':
            alignment=anchor.locate(before_map)
            if not alignment:raise RuntimeError('Safe return map cannot be aligned')
            current=anchor.project(before_map['player'],alignment);delta=anchor.spawn_point[1]-current[1]
            if abs(current[0]-anchor.spawn_point[0])>15 or not 0<delta<110:raise RuntimeError('Safe restore is restricted to the initial stem below the observed NPC')
            profiles=json.loads((ROOT/'evaluations/v3/input-profile.json').read_text(encoding='utf-8'));walks=[p for p in profiles if p['mode']=='move' and p['anchor_id']==anchor.identity]
            if not walks:raise RuntimeError('Measured walk profile unavailable')
            args.direction='down';args.ms=max(40,delta/walks[-1]['reference_pixels_per_ms'])
        start=time.perf_counter();backend.connect();startup_ms=(time.perf_counter()-start)*1000
        print(json.dumps({'connected':True,'startup_ms':startup_ms,'folder':str(session.folder)}),flush=True)
        if args.op!='connect':
            session.transition('jogo');frame,f=session.capture('before-continuous-input')
            if f['scene']!='jogo' or f['enemy_count'] or f['hazard_count'] or not f['player'] or f['health']<.8:raise RuntimeError('Safe input-test preconditions not met')
            neutral=cv2.imread(str(ROOT/'data/v2/v2_calibration_45124c972be4410b/0048-after-jogo.jpg'))
            interaction=InteractionVision(ROOT);returning=False
            can_run=lambda:float(cv2.matchTemplate(InteractionVision.mask(frame),InteractionVision.mask(neutral),cv2.TM_CCOEFF_NORMED)[0,0])>.92
            def save_action(row):
                memory.remember('episodic','v3_continuous_action',session.scope,{'run_id':session.run_id,**row},Provenance('v3:input_probe',method='persistent_touch_with_explicit_up'),.9,'uncertain')
            controller=ContinuousActions(backend,json.loads((ROOT/'config.json').read_text())['controls'],session.cancel,[ROOT/'data/v3/STOP',ROOT/'data/v2/STOP'],can_run,save_action)
            def policy(snap):
                f=snap['features']
                if f['scene']!='jogo':return 'screen_changed'
                if f['health'] is not None and f['health']<.75:return 'health_drop'
                if f['enemy_count'] or f['hazard_count']:return 'unexpected_threat'
                if not returning and args.op in ('move','run','combined','sequence','interrupt') and interaction.affordance(snap['frame']):return 'npc_checkpoint'
            def observed_call(method,**kwargs):
                observer=LiveObserver(session).start()
                try:return method(monitor=lambda:observer.reason(policy),**kwargs)
                finally:observations.append(observer.close())
            if args.op=='interrupt':
                def cancel():
                    global cancel_at
                    time.sleep(.45);cancel_at=time.perf_counter();session.cancel.set()
                thread=threading.Thread(target=cancel,daemon=True);thread.start()
                try:observed_call(controller.move_hold,direction=args.direction,duration_ms=args.ms)
                except InterruptedError:pass
                thread.join();result={'stops':controller.stops,'actions':controller.actions,'cancel_at':cancel_at}
            elif args.op in ('move','run','restore'):
                if args.op=='restore':returning=True
                result=observed_call(controller.move_hold,direction=args.direction,duration_ms=args.ms,run=args.op=='run')
            elif args.op=='combined':result=observed_call(controller.move_attack_hold,direction=args.direction,duration_ms=args.ms)
            elif args.op=='sequence':
                sequence=[{'op':'move_hold','direction':args.direction,'duration_ms':args.ms/4} for _ in range(4)]
                rows=observed_call(controller.execute_sequence,actions=sequence);result={'sequence':rows,'actual_ms':sum(r['actual_ms'] for r in rows),'outcome':rows[-1]['outcome']}
            else:result=observed_call(controller.attack_hold,duration_ms=args.ms)
            backend.release_all();session.transition('pausa');frame,_=session.capture('after-continuous-map');after_map=PauseMap().parse(frame)
            motion=anchor.motion(before_map,after_map,args.direction if args.direction in ('up','down','left','right') else 'up')
            result={'control':result,'map_motion':motion,'stage_complete':False}
            if args.op=='restore':result['returned_to_spawn']=anchor.is_spawn(after_map)
            memory.remember('episodic','v3_segment_verification',session.scope,{'run_id':session.run_id,'op':args.op,'result':motion,'frame':session.last_features['frame'],'claim':'aggregate displacement of this bounded segment, not stage completion'},Provenance(session.last_features['frame'],method='aligned_before_after_map'),.95,'verified' if motion.get('verified') else 'uncertain')
            if args.op in ('move','run') and motion.get('verified') and result['control']['outcome']=='duration_elapsed':
                profile_path=ROOT/'evaluations/v3/input-profile.json';profiles=json.loads(profile_path.read_text(encoding='utf-8')) if profile_path.exists() else []
                sample={'run_id':session.run_id,'mode':args.op,'direction':args.direction,'requested_ms':args.ms,'actual_ms':result['control']['actual_ms'],'reference_pixels':motion['direction_progress'],'reference_pixels_per_ms':motion['direction_progress']/result['control']['actual_ms'],'anchor_id':anchor.identity}
                profiles.append(sample);profile_path.write_text(json.dumps(profiles,indent=2),encoding='utf-8');result['profile']=sample
            if args.roundtrip and anchor.is_spawn(after_map):result['returned_to_spawn']=True
            elif args.roundtrip and args.op in ('move','run','combined','sequence') and motion.get('verified'):
                if args.direction!='up' or abs(motion['dx'])>15 or not 5<motion['direction_progress']<190:raise RuntimeError('Roundtrip is restricted to the observed safe initial vertical corridor')
                profiles=json.loads((ROOT/'evaluations/v3/input-profile.json').read_text(encoding='utf-8'))
                walks=[p for p in profiles if p['mode']=='move' and p['direction']=='up' and p['anchor_id']==anchor.identity]
                if not walks:raise RuntimeError('Measured walking profile required before return')
                duration=motion['direction_progress']/walks[-1]['reference_pixels_per_ms']
                if duration>5000:raise RuntimeError('Return exceeds the calibrated corridor action bound')
                session.transition('jogo');frame,f=session.capture('before-return')
                if f['enemy_count'] or f['hazard_count'] or f['health']<.8:raise RuntimeError('Return preconditions changed')
                returning=True
                result['return_control']=observed_call(controller.move_hold,direction='down',duration_ms=duration)
                session.transition('pausa');frame,_=session.capture('returned-map');result['returned_to_spawn']=anchor.is_spawn(PauseMap().parse(frame))
    except Exception as exc:error=type(exc).__name__+': '+str(exc)
    finally:
        try:
            if controller:controller.close()
        except Exception as exc:error=(error or '')+'; controller close: '+str(exc)
        backend_result=backend.close()
        try:session.transition('pausa')
        except Exception as exc:error=(error or '')+'; pause: '+str(exc)
        report=session.close();report.update(op=args.op,result=result,error=error,backend=backend_result,continuous_actions=controller.actions if controller else [],observations=observations,stage_complete=False)
        (session.folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');memory.close()
        print(json.dumps({'folder':str(session.folder),'result':result,'error':error,'release_errors':backend_result['release_errors']},ensure_ascii=False),flush=True)
