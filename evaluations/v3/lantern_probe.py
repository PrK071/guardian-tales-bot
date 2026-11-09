"""Bounded V3 object-transfer/ignition test from the current observed room."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from bot import ADB
from cognitive.contracts import uid,Task,State
from cognitive.memory import Memory
from cognitive.lantern_control import LanternController
from cognitive.v3.session import GameplaySession

parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['pickup','ignite','recover','combat','view','light','rock','drill','escape','verify-light','gate']);parser.add_argument('--source');parser.add_argument('--direction',choices=['up','down'],default='up');parser.add_argument('--target',nargs=2,type=float);args=parser.parse_args()
memory=Memory(ROOT/'data/cognitive.sqlite');goal=memory.goal('V3 lantern substep validation');task=Task(uid('v3_lantern_task'),goal,'lantern_substep',args.mode,'world:1:passage:1',success={'verified':True},state=State.RUNNING);memory.save_task(task)
s=GameplaySession(ROOT,ADB(),memory,run_id=uid('v3_lantern_probe'),video=True);s.kind='bounded_lantern_substep_not_stage_completion';s.goal_id=goal;s.task_id=task.id;error=None;result=None
try:
    c=LanternController(s,seconds=120)
    if args.mode=='recover':
        from cognitive.v3.pickup_recovery import recover_pickup
        result=recover_pickup(s,args.source)
    elif args.mode=='combat':
        from cognitive.v3.carry_combat import fight_with_carried_item
        result=fight_with_carried_item(s);result['verified']=result['visible_combat_ended']
    elif args.mode=='gate':
        from cognitive.v3.lantern_gate import verify_and_cross
        c.restore_held();result=verify_and_cross(s)
    elif args.mode=='verify-light':
        from cognitive.v3.fixed_lanterns import verify_fixed_from_source
        c.restore_held();result=verify_fixed_from_source(s,c,args.source)
    elif args.mode=='escape':
        from cognitive.v3.rock_glove import escape_cleared_tile
        result=escape_cleared_tile(s)
    elif args.mode=='drill':
        from cognitive.v3.rock_glove import drill_visible
        result=drill_visible(s)
    elif args.mode=='rock':
        from cognitive.v3.carry_combat import arrow_visible
        from cognitive.contracts import Action
        c.restore_held();s.pulse(Action('move',{'direction':'left','ms':100},'Face observed clear room floor before releasing the torch for Mole Glove prerequisite'))
        s.pulse(Action('interact',{'ms':100},'Release carried torch to free the observed puzzle tool control'));s.held_object_kind=None
        frame,f=s.capture('v3-rock-tool-free');released=not arrow_visible(s,frame)
        if not released:raise RuntimeError('Torch release not verified')
        s.pulse(Action('move',{'direction':args.direction,'ms':200 if args.direction=='down' else 100},'Face the observed cracked rock for the reported Mole Glove prerequisite'))
        frame,f=s.capture('v3-rock-tool-affordance');result={'verified':released,'frame':f['frame'],'stage_complete':False}
    elif args.mode=='light':
        from cognitive.v3.fixed_lanterns import light_nearest
        c.restore_held();result=light_nearest(s,c)
    elif args.mode=='view':
        from cognitive.v3.carry_combat import arrow_visible
        s.transition('jogo');frame,f=s.capture('v3-view-carry-check')
        if arrow_visible(s,frame):c.restore_held()
        try:
            for _ in range(3):
                result=s.navigate_to(args.target,tolerance=7,allow_npc_bypass=True)
                if result.get('verified') or not result.get('progress_verified'):break
        except ValueError:
            from cognitive.v3.room_navigation import navigate_room
            result=navigate_room(s,args.target)
    else:result=c.pickup() if args.mode=='pickup' else c.ignite()
    task.state=State.COMPLETED if result.get('verified') else State.BLOCKED
except Exception as exc:error=type(exc).__name__+': '+str(exc);task.state=State.BLOCKED
finally:
    memory.save_task(task);memory.goal_state(goal,task.state)
    try:s.transition('pausa')
    except Exception as exc:error=(error or '')+'; pause: '+str(exc)
    report=s.close();report.update(mode=args.mode,result=result,error=error,events=getattr(locals().get('c'),'events',[]));(s.folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');memory.close();summary={k:v for k,v in (result or {}).items() if k in ('verified','visible_combat_ended','outcome','confirmations','source_separation_world_pixels','after','goal_error_reference_pixels')};print(json.dumps({'folder':str(s.folder),'result':summary,'error':error}),flush=True)
