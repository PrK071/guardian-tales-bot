"""Verify the observed lowering stone, then cross its formerly blocked edge."""
import math
import cv2
import numpy as np
from ..contracts import Provenance
from ..map_navigation import PauseMap
from ..spatial import SpatialVision
from .room_navigation import goto_room_checkpoint

SOURCE='data/v3/v3_lantern_probe_e1bb4aa9ddb84c44/0002-lantern-find-object.jpg'
SOURCE_MAP='data/v3/v3_lantern_probe_e1bb4aa9ddb84c44/0004-after-pausa.jpg'
PANEL=[408,598,210,100]

def lowered_stone_evidence(s,frame,current_actor_reference=None):
    before=cv2.imread(str(s.root/SOURCE));x,y,w,h=PANEL
    if current_actor_reference is not None:
        old_state=PauseMap().parse(cv2.imread(str(s.root/SOURCE_MAP)));alignment=s.map_anchor.locate(old_state)
        if not alignment:return {'verified':False,'reason':'closed_gate_reference_unavailable'}
        old_actor=s.map_anchor.project(old_state['player'],alignment);ratio=.44/s.speeds['move'];actor=s.last_features.get('player')
        if not actor:return {'verified':False,'reason':'current_actor_unavailable'}
        motion={'background_dx':actor[0]-800.5+(old_actor[0]-current_actor_reference[0])*ratio,'background_dy':actor[1]-445+(old_actor[1]-current_actor_reference[1])*ratio,'confidence':.9,'method':'independent_aligned_map_checkpoints_and_measured_scale'}
    else:motion=SpatialVision.motion(before,frame,None,None)
    if motion['confidence']<.25:return {'verified':False,'reason':'gate_landmark_alignment_unavailable','motion':motion}
    xx=round(x+motion['background_dx']);yy=round(y+motion['background_dy'])
    if not(320<=xx and xx+w<=1090 and 150<=yy and yy+h<=820):return {'verified':False,'reason':'gate_panel_outside_unoccluded_view','motion':motion}
    old=before[y:y+h,x:x+w];current=frame[yy:yy+h,xx:xx+w]
    score=float(cv2.matchTemplate(cv2.cvtColor(current,cv2.COLOR_BGR2GRAY),cv2.cvtColor(old,cv2.COLOR_BGR2GRAY),cv2.TM_CCOEFF_NORMED)[0,0])
    exposed=float(np.mean(SpatialVision.floor_mask(frame)[yy:yy+h,xx:xx+w]>0))
    return {'verified':bool(score<.45 and exposed>.65),'closed_panel_correlation':score,'exposed_floor_fraction':exposed,'current_panel':[xx,yy,w,h],'motion':motion,'closed_frame':SOURCE}

def gate_reference(s):
    old=PauseMap().parse(cv2.imread(str(s.root/SOURCE_MAP)));alignment=s.map_anchor.locate(old)
    if not alignment:raise RuntimeError('Closed-gate map source does not align to this stage')
    actor=s.map_anchor.project(old['player'],alignment);ratio=.44/s.speeds['move'];x,y,w,h=PANEL
    # The complete closed stone extends another 120 pixels below this top
    # panel. Cross beyond that whole former footprint, not just its first edge.
    return [actor[0]+(x+w/2-800.5)/ratio,actor[1]+(y+220-445)/ratio]

def verify_and_cross(s):
    goto_room_checkpoint(s,[426,775]);_,_,view_actor,_=s.map_state('v3-gate-registered-view-map');s.transition('jogo');proofs=[]
    for _ in range(2):
        frame,f=s.capture('v3-lantern-gate-lowered-check');proof=lowered_stone_evidence(s,frame,view_actor);proof['frame']=f['frame'];proofs.append(proof)
        if not proof['verified']:raise RuntimeError('Lowered lantern barrier is not currently verified: '+proof.get('reason','panel still present or floor absent'))
    edge=gate_reference(s);target=[edge[0],edge[1]+10]
    interrupted=False
    for _ in range(4):
        try:result=s.navigate_to(target,tolerance=6,allow_npc_bypass=True,max_segment_ms=1200)
        except ValueError:
            from .room_navigation import navigate_room
            result=navigate_room(s,target,tolerance=6,max_actions=8)
        if result.get('reason')=='enemy_detected':interrupted=True;break
        if result.get('verified'):break
        if not result.get('progress_verified'):raise RuntimeError('Opened gate route failed to progress')
    _,_,after,map_features=s.map_state('v3-lantern-gate-crossing-map')
    verified=bool(after[1]>edge[1] and abs(after[0]-edge[0])<18)
    result={'verified':verified,'lowered_stone_observations':proofs,'formerly_blocked_edge_reference':edge,'target_reference':target,'after_reference':after,'crossing_map_frame':map_features['frame'],'enemy_interrupted':interrupted,'stage_complete':False}
    active=s.memory.retrieve(s.scope,kind='v3_active_plan',include_global=False,limit=1)
    result['entry_token']=active[0]['content'].get('entry_token') if active else None
    s.memory.remember('episodic','v3_lantern_gate_crossing',s.scope,{'run_id':s.run_id,**result},Provenance(map_features['frame'],method='two_aligned_stone_lowering_observations_then_independent_map_crossing'),.95,'verified' if verified else 'uncertain')
    if not verified:raise RuntimeError('Map did not confirm crossing the complete former gate footprint')
    return result

def traverse_open_gate(s,target_y=820):
    """Execute the cached open-gate route; its orange slabs fail brown-floor CV."""
    import time
    from .observation import LiveObserver,ThreatGate
    active=s.memory.retrieve(s.scope,kind='v3_active_plan',include_global=False,limit=1)
    proofs=s.memory.retrieve(s.scope,kind='v3_lantern_gate_crossing',include_global=False,limit=4)
    entry=active[0]['content'].get('entry_token') if active else None
    proof=next((r for r in proofs if r['validation']=='verified' and r['content'].get('entry_token')==entry),None)
    if not entry or not proof:raise RuntimeError('No verified open barrier for this stage entry')
    _,_,before,before_features=s.map_state('v3-open-gate-sequence-before')
    if not(396<=before[0]<=455 and 748<=before[1]<=825):raise RuntimeError('Actor is outside the verified gate route region')
    target=[440,target_y];sequence=[];speed=s.speeds['move']
    if abs(before[0]-target[0])>4:sequence.append({'op':'move_hold','direction':'right' if before[0]<440 else 'left','duration_ms':abs(before[0]-440)/speed})
    if abs(before[1]-target_y)>4:sequence.append({'op':'move_hold','direction':'down' if before[1]<target_y else 'up','duration_ms':abs(before[1]-target_y)/speed})
    s.transition('jogo');_,features=s.capture('v3-open-gate-sequence-preflight')
    if features['scene']!='jogo' or not features.get('player') or features['health'] is not None and features['health']<.25:raise RuntimeError('Open-gate route preflight unavailable')
    if s.preflight_enemy(features):return {'verified':False,'reason':'enemy_detected','before':before,'target':target}
    if not sequence:return {'verified':True,'already_at_checkpoint':True,'after':before,'target':target}
    s.prepare_continuous('verified_open_gate_route',{'source_memory':proof['id'],'sequence':sequence,'before':before,'target':target})
    observer=LiveObserver(s).start();threat=ThreatGate();missing=0;last=-1;began=time.perf_counter()
    def policy(snapshot):
        nonlocal missing,last
        f=snapshot['features']
        if f['scene']!='jogo':return 'screen_changed'
        if f['health'] is not None and f['health']<.25:return 'low_health'
        if threat.update(snapshot):return 'enemy_detected'
        if snapshot['sequence']!=last:last=snapshot['sequence'];missing=0 if f.get('player') else missing+1
        if missing>=2:return 'actor_lost'
    try:controls=s.controls.execute_sequence(sequence,monitor=lambda:observer.reason(policy))
    finally:s.backend.release_all();observations=observer.close()
    _,_,after,features=s.map_state('v3-open-gate-sequence-after');error=math.dist(after,target)
    result={'verified':error<=7,'progress_verified':math.dist(before,after)>3,'before':before,'after':after,'target':target,'reason':controls[-1]['outcome'],'goal_error_reference_pixels':error,'source_memory':proof['id'],'controls':controls,'observations':observations,'seconds':time.perf_counter()-began,'before_frame':before_features['frame'],'after_frame':features['frame'],'model_calls':0}
    s.verify_continuous(result,result['verified']);s.segment_results.append(result)
    s.memory.remember('episodic','v3_open_gate_sequence',s.scope,{'run_id':s.run_id,**result},Provenance(features['frame'],method='same_entry_verified_lowering_and_crossing_then_calibrated_route_with_live_guards_and_map_endpoint'),.95,'verified' if result['verified'] else 'uncertain')
    if not result['verified'] and not result['progress_verified']:raise RuntimeError('Verified open-gate sequence did not progress')
    return result
