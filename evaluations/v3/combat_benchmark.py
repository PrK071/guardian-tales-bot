"""Fresh first-chamber encounters, alternating legacy and V3 controllers.

Same account/party/stage and shared observed prefix. NPC contributions remain
part of BOTH conditions; this measures encounter completion, not solo DPS.
"""
from pathlib import Path
import argparse,json,math,subprocess,sys,time,urllib.request
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from bot import ADB
from cognitive.contracts import uid
from cognitive.fast_control import FastSession
from cognitive.memory import Memory
from cognitive.v3.session import GameplaySession

class TimedADB(ADB):
    def __init__(self):super().__init__();self.inputs=[]
    def hold(self,x,y,ms,w,h):
        row={'point':[x,y],'requested_ms':ms,'start':time.perf_counter()}
        try:return super().hold(x,y,ms,w,h)
        finally:row['end']=time.perf_counter();self.inputs.append(row)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repeats',type=int,default=3);parser.add_argument('--resume-first-entry');parser.add_argument('--modes',nargs='+',choices=['v2','v3_video'],default=['v2','v3_video']);parser.add_argument('--append-to');args=parser.parse_args()
    if not 1<=args.repeats<=3:raise RuntimeError('Use 1..3 controlled repetitions')
    try:urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=1)
    except Exception:pass
    else:raise RuntimeError('Stop main server before standalone benchmark')
    folder=ROOT/'data/v3'/(args.append_to or uid('v3_combat_benchmark'))
    if folder.resolve().parent!=(ROOT/'data/v3').resolve():raise RuntimeError('Benchmark must stay in project data/v3')
    folder.mkdir(exist_ok=bool(args.append_to));cases=json.loads((folder/'cases.json').read_text()) if args.append_to else []
    rows=[json.loads(line) for line in (ROOT/'data/v2/v2_lantern_calibration_cface23508d84a6d/navigation.jsonl').read_text().splitlines()];targets=[rows[i]['aligned_map_motion']['after'] for i in (0,1,6,7)]
    for repetition in range(args.repeats):
        for mode in args.modes:
            if any(c['mode']==mode and c['repetition']==repetition and (c.get('seconds') is not None or c.get('combat_started')) for c in cases):continue
            if (ROOT/'data/v3/STOP').exists() or (ROOT/'data/v2/STOP').exists():raise InterruptedError('Manual stop')
            label=f'{repetition}-{mode}';print(json.dumps({'case':label,'status':'preparing fresh entry'}),flush=True)
            resumed=None
            if args.resume_first_entry and repetition==0 and mode=='v2':
                previous=json.loads((ROOT/'data/v3'/args.resume_first_entry/'cases.json').read_text())[0]
                if previous.get('error')!='RuntimeError: Expected first encounter not currently visible; no matched comparison' or not previous.get('initial_spawn_verified') or previous.get('initial_features',{}).get('enemy_count'):raise RuntimeError('Cannot resume this failed setup as a fresh encounter')
                resumed=previous
            else:
                with (folder/f'{label}-preparation.log').open('w',encoding='utf-8') as log:
                    subprocess.run([sys.executable,'-X','utf8',str(ROOT/'evaluations/v2/prepare_initial.py')],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=100,cwd=ROOT)
            memory=Memory(ROOT/'data/cognitive.sqlite');prep=None;s=None;case={'mode':mode,'repetition':repetition,'error':None}
            try:
                prep=GameplaySession(ROOT,TimedADB(),memory,run_id=uid('v3_combat_setup'))
                state,_,current,_=prep.map_state('matched-spawn')
                if resumed:
                    if math.dist(current,resumed['start_reference'])>4:raise RuntimeError('Resumed setup pose differs; no combat benchmark sent')
                    case['resumed_verified_precombat_setup']=args.resume_first_entry
                elif not prep.map_anchor.is_spawn(state):raise RuntimeError('Fresh initial spawn not verified')
                case['initial_spawn_verified']=True
                triggered=False
                for target in targets:
                    if resumed and target[1]>=current[1]-5:continue
                    for attempt in range(3):
                        result=prep.navigate_to(target,tolerance=7,allow_npc_bypass=True)
                        if result.get('reason')=='enemy_detected':triggered=True;break
                        if result.get('verified'):break
                        if not result.get('progress_verified'):raise RuntimeError('Shared prefix failed to progress')
                    else:raise RuntimeError('Shared prefix checkpoint not reached')
                    if triggered:break
                _,_,point,_=prep.map_state('matched-combat-start-map');case['start_reference']=point;case['setup_run']=prep.run_id
                prep.close();prep=None
                adb=TimedADB()
                s=GameplaySession(ROOT,adb,memory,run_id=uid('v3_matched_combat'),video=True) if mode=='v3_video' else FastSession(ROOT,adb,memory,run_id=uid('v2_matched_combat'),artifact_base='data/v3')
                s.kind='matched_first_encounter_not_stage_completion';s.capture('matched-paused-ready');begun=time.perf_counter();s.transition('jogo')
                _,initial=s.capture('matched-initial-enemies')
                for _ in range(6):
                    if initial['enemy_count']:break
                    _,initial=s.capture('matched-initial-enemy-reobservation')
                case['initial_features']=initial
                if not initial['enemy_count']:raise RuntimeError('Expected first encounter not currently visible; no matched comparison')
                case.update(combat_started=True,run_id=s.run_id)
                result=s.fight_continuously(45) if mode=='v3_video' else s.fight(45)
                case.update(seconds=time.perf_counter()-begun,result=result,run_id=s.run_id,legacy_inputs=adb.inputs,visible_combat_ended=result.get('visible_combat_ended',False))
                _,confirmation=s.capture('matched-independent-raw-end');case['end_features']=confirmation
                if confirmation.get('combat_present',confirmation['enemy_count']):case['visible_combat_ended']=False;case['error']='Controller reported absence while raw enemy evidence remained'
                s.transition('pausa');case['final_frame']=s.last_features['frame']
            except Exception as exc:
                case['error']=type(exc).__name__+': '+str(exc)
                if case.get('combat_started'):case.update(seconds=time.perf_counter()-begun,visible_combat_ended=False,legacy_inputs=adb.inputs,timing_scope='elapsed_until_controller_failure_not_completion')
            finally:
                for session in (prep,s):
                    if session:
                        try:
                            if session.last_features and session.last_features['scene']=='jogo':session.transition('pausa')
                        finally:session.close()
                memory.close();cases.append(case)
                (folder/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'case':label,'seconds':case.get('seconds'),'clear':case.get('visible_combat_ended'),'error':case['error'],'folder':str(folder)}),flush=True)
            if case['error'] and case.get('seconds') is None:raise RuntimeError('Stop matched series after failed preparation; inspect recorded evidence')
    print(json.dumps({'folder':str(folder),'completed_cases':len(cases)}),flush=True)
if __name__=='__main__':main()
