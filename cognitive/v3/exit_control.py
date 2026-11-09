"""Observed final-corridor exit and two independent real completion checks."""
import math,time
from pathlib import Path
import cv2
import numpy as np
from ..contracts import Action,Provenance
from ..spatial import SpatialVision
from ..stage_v2 import completion_evidence,InteractionVision
from .observation import LiveObserver,ThreatGate
from .exploration import visible_floor_horizon

def verified_exit_context(s,arrival,map_frame):
    """A filled map star alone cannot establish completion of this run."""
    rows=s.memory.retrieve(s.scope,kind='v3_active_plan',include_global=False,limit=1)
    if not rows:raise RuntimeError('No active stage entry for exit verification')
    active=rows[0]['content'];states=active.get('states',{});gate=states.get('lantern_puzzle',{});combat=states.get('final_encounter',{});result=combat.get('result',{})
    combat_verified=bool(result.get('visible_combat_ended') or result.get('result',{}).get('visible_combat_ended') or result.get('source',{}).get('visible_combat_ended'))
    if not(active.get('entry_token') and gate.get('state')=='completed' and gate.get('result',{}).get('verified') and combat.get('state')=='completed' and combat_verified):raise RuntimeError('This entry lacks verified gate and final encounter objectives')
    path=(s.root/map_frame).resolve()
    if not path.is_relative_to(s.folder.resolve()) or not path.exists() or not arrival or arrival[1]<930 or abs(arrival[0]-425.5)>30:raise RuntimeError('No current-run final-corridor map arrival')
    return {'entry_token':active['entry_token'],'plan_id':active['plan_id'],'arrival_reference':arrival,'arrival_map_frame':map_frame,'gate_objective_frame':gate['frame'],'combat_objective_frame':combat['frame'],'current_entry_verified':True}

def house_candidate(frame,features):
    player=features.get('player')
    if not player:return None
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV);white=cv2.inRange(hsv,(0,0,210),(180,55,255));white[:max(180,round(player[1]+45))]=0;white[820:]=0;white[:,:550]=0;white[:,1090:]=0
    contours,_=cv2.findContours(white,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);found=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if not(20<=w<=80 and 22<=h<=90 and .55<w/h<1.35 and cv2.contourArea(contour)>150):continue
        roi=frame[max(0,y-3):min(900,y+h+4),max(0,x-3):min(1600,x+w+4)];dark=float(np.mean(np.max(roi,axis=2)<95))
        if dark<.25 or abs(x+w/2-player[0])>120:continue
        found.append({'bbox':[x,y,w,h],'point':[x+w/2,y+h/2],'dark_fraction':dark,'method':'white_house_in_dark_floor_marker_in_final_corridor'})
    return min(found,key=lambda row:math.dist(row['point'],player)) if found else None

def completed_passage_card(frame,root):
    reference=cv2.imread(str(root/'data/v2/recovery-world.png'))
    if reference is None:return {'verified':False,'reason':'map_card_reference_unavailable'}
    template=reference[419:481,842:894];search=cv2.cvtColor(frame[150:730,250:1350],cv2.COLOR_BGR2GRAY);best=None
    for scale in (value/100 for value in range(94,119)):
        candidate=cv2.resize(template,None,fx=scale,fy=scale);scores=cv2.matchTemplate(search,cv2.cvtColor(candidate,cv2.COLOR_BGR2GRAY),cv2.TM_CCOEFF_NORMED);_,score,_,(x,y)=cv2.minMaxLoc(scores)
        if best is None or score>best[0]:best=(score,x+250+candidate.shape[1]/2,y+150+candidate.shape[0]/2,scale)
    score,cx,cy,scale=best
    if score<.90:return {'verified':False,'reason':'passage_card_not_identified','card_score':score}
    x1=round(cx-30*scale);x2=round(cx+30*scale);y1=round(cy+38*scale);y2=round(cy+78*scale);roi=frame[y1:y2,x1:x2]
    if not roi.size:return {'verified':False,'reason':'star_label_outside_frame'}
    hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV);gold=cv2.inRange(hsv,(16,110,205),(43,255,255));bright_core=cv2.inRange(hsv,(0,0,220),(180,110,255));lit=gold|bright_core;dark=float(np.mean(np.max(roi,axis=2)<100));contours,_=cv2.findContours(lit,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    stars=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if not(cv2.contourArea(contour)>70 and 12<=w<=40 and 12<=h<=40 and x>=3 and y>=2 and x+w<=gold.shape[1]-3 and y+h<=gold.shape[0]-2):continue
        if abs(x+w/2-gold.shape[1]/2)>10*scale:continue
        filled=np.zeros_like(gold);cv2.drawContours(filled,[contour],-1,255,-1);inside=filled>0
        fraction=float(np.mean(gold[inside]>0)) if np.any(inside) else 0
        lit_fraction=float(np.mean(lit[inside]>0)) if np.any(inside) else 0
        gold_pixels=int(np.count_nonzero(gold[inside]))
        moments=cv2.moments(contour)
        if not moments['m00']:continue
        sx=round(moments['m10']/moments['m00']);sy=round(moments['m01']/moments['m00'])
        center=hsv[max(0,sy-2):sy+3,max(0,sx-2):sx+3]
        center_bright=float(np.mean(center[:,:,2]>180)) if center.size else 0
        # An uncompleted star has the same outer silhouette. Its dark hollow
        # centre and sparse gold rim must never count as a filled star.
        # The completed star has a white core in raw pixels. JPEG blending
        # can hide that split, so contour gold plus its bright core while
        # requiring a filled silhouette, real gold and a bright centre.
        if lit_fraction>=.85 and gold_pixels>=70 and center_bright>=.70:stars.append({'bbox':[x,y,w,h],'gold_fill_fraction':fraction,'lit_fill_fraction':lit_fraction,'gold_pixels':gold_pixels,'bright_center_fraction':center_bright})
    return {'verified':bool(stars and dark>.30),'card_score':float(score),'card_center':[cx,cy],'star_roi':[x1,y1,x2-x1,y2-y1],'bright_gold_pixels':int(np.count_nonzero(gold)),'dark_label_fraction':dark,'star_shapes':stars}

def verify_exit_result(s,runtime,bot,house,context,seconds=45):
    began=time.monotonic();deadline=began+seconds;observations=[];kind=None;scenes=[]
    house_path=(s.root/house['frame']).resolve() if house else None
    valid_transition=bool(context and context.get('current_entry_verified') and context.get('controls_issued') and context.get('exit_interaction_issued') and house_path and house_path.is_relative_to(s.folder.resolve()) and house_path.exists())
    while time.monotonic()<deadline:
        s.check_cancel();ob=runtime.environment.observe();runtime.evidence(ob);frame=runtime.environment.last_frame
        if not scenes or scenes[-1]['frame']!=ob.frame_path:scenes.append({'scene':ob.scene,'frame':ob.frame_path,'elapsed_seconds':time.monotonic()-began})
        if completion_evidence(bot.snapshot):proof={'verified':True,'kind':'stage_result_text'}
        elif valid_transition and ob.scene=='mapa' and not ob.blocked:
            from ..perception import normalize
            text=normalize(ob.text);compact=text.replace(' ','')
            proof={**completed_passage_card(frame,s.root),'kind':'identified_passage_card_with_filled_star_after_observed_exit'} if 'mundo1florestakanterbury' in compact or 'mundo 1' in text and 'kanterbury' in text else {'verified':False,'reason':'expected_world_not_observed'}
        else:proof={'verified':False,'scene':ob.scene}
        if proof['verified']:
            if kind!=proof['kind']:observations=[]
            kind=proof['kind']
            if not any(row['observation_id']==ob.id or row['frame']==ob.frame_path for row in observations):observations.append({'observation_id':ob.id,'frame':ob.frame_path,'proof':proof})
            if len(observations)>=2:
                result={'stage_complete':True,'verified':True,'result_evidence':[r['observation_id'] for r in observations],'result_observations':observations,'exit_landmark':house,'exit_context':context,'verification_seconds':time.monotonic()-began,'observed_scenes':scenes,'model_calls':0}
                s.memory.remember('episodic','v3_stage_exit_verified',s.scope,{'run_id':s.run_id,**result},Provenance(ob.frame_path,method='observed_final_corridor_exit_then_two_independent_stage_result_or_identified_filled_star_observations'),.98,'verified');return result
        else:observations=[];kind=None
    return None

def visible_exit_detour(frame,features,objects=()):
    """Take one checked flank segment around an observed forward obstruction."""
    from .segments import SegmentPlanner,clear_line
    player=features.get('player')
    if not player:return None
    floor=SpatialVision.floor_mask(frame);px,py=player;cv2.circle(floor,(round(px),round(py)),36,255,-1)
    # Match the existing local controller's actor-occlusion treatment. The
    # known sprite may hide clearance above the feet, while the follower
    # below them remains an obstacle to go around.
    for sy in range(max(0,int(py-110)),min(900,int(py+13))):
        left,right=int(px-95),int(px+95)
        if 0<=left<right<1600 and floor[sy,left] and floor[sy,right]:floor[sy,max(0,int(px-80)):min(1600,int(px+81))]=255
    obstacles=[e for e in features.get('entities',[]) if e['kind'] in ('hazard','rock_obstacle_candidate','bomb_candidate')]+[o for o in objects if o['kind']=='portable_brazier']
    for obj in obstacles:
        x,y,w,h=map(round,obj['bbox']);floor[max(0,y):min(900,y+h),max(0,x):min(1600,x+w)]=0
    clearance=cv2.distanceTransform(floor,cv2.DIST_L2,5)
    for distance in (320,260,200):
        target=[px,min(800,py+distance)]
        try:plan=SegmentPlanner(.44).plan({'floor':floor,'player':player},target,margin=28)
        except ValueError:continue
        if not plan['segments'] or plan['segments'][-1]['end'][1]-py<100:continue
        first=plan['segments'][0];vx,vy=first['direction'];ms=max(80,min(1200,round(first['duration_ms'])));end=[px+vx*ms*.44,py+vy*ms*.44]
        if vy<-.01 or abs(end[0]-px)>180 or not clear_line(clearance,player,end,28,start_escape=True):continue
        return {'direction':list(first['direction']),'duration_ms':ms,'source_frame':features['frame'],'forward_target':target,'predicted_endpoint':end,'clearance_pixels':28,'observed_obstacles':obstacles,'plan':plan,'scope':'one visible flank segment; forward continuation requires a new observation'}
    return None

def recenter_exit_after_stall(s,position):
    """One visible lateral leg, then independent same-height map arrival."""
    from ..puzzle_control import BombRockController
    delta=425.5-position[0]
    if not 5<abs(delta)<=30 or position[1]<930:raise RuntimeError('Exit stall has no bounded lateral recovery')
    s.transition('jogo')
    for _ in range(3):
        frame,f=s.capture('v3-exit-stall-lateral-preflight')
        if f.get('scene')!='jogo' or not f.get('player') or f.get('health') is not None and f['health']<.25 or s.preflight_enemy(f):raise RuntimeError('Exit lateral recovery preflight failed')
        target=[f['player'][0]+delta*.44/s.speeds['move'],f['player'][1]]
        try:heading,ms=BombRockController.local_approach(frame,f,target)
        except RuntimeError:continue
        if heading==('right' if delta>0 else 'left') and ms<=600:break
    else:raise RuntimeError('Exit lateral recovery requires one clear bounded horizontal leg')
    if hasattr(s,'failure_checkpoint'):s.failure_checkpoint('Exit wall stall: exact lateral recovery preflight',frame,f)
    control=s.pulse(Action('move',{'direction':heading,'ms':ms},'Leave the independently confirmed exit wall stall along currently observed lateral floor'))
    _,_,after,checkpoint=s.map_state('v3-exit-stall-lateral-arrival')
    verified=bool(abs(after[0]-425.5)<=4 and abs(after[1]-position[1])<=4)
    return {'verified':verified,'before':list(position),'after':list(after),'target_reference':[425.5,position[1]],'after_frame':checkpoint['frame'],'preflight_frame':f['frame'],'control':control,'goal_reached':False,'stage_complete':False}


def exit_forward(s,runtime,bot,arrival,map_frame,max_actions=10):
    context=verified_exit_context(s,arrival,map_frame)
    s.transition('jogo');house=getattr(s,'exit_house_evidence',None);actions=[];detour_positions=[list(arrival)];last_map_position=list(arrival);recentered=False
    for _ in range(max_actions):
        s.check_cancel();frame,f=s.capture_live('v3-exit-forward-observe')
        if f['scene']!='jogo':
            result=verify_exit_result(s,runtime,bot,house,context)
            if result:result['exit_actions']=actions;return result
            raise RuntimeError('Exit changed screen without independently verified completion')
        if not f.get('player'):
            if house:
                result=verify_exit_result(s,runtime,bot,house,context)
                if result:result['exit_actions']=actions;return result
            raise RuntimeError('Final-corridor actor observation unavailable')
        if f['health'] is not None and f['health']<.25:raise RuntimeError('Final-corridor health guard')
        if s.preflight_enemy(f):
            combat=s.fight_continuously(45)
            if not combat['visible_combat_ended']:raise RuntimeError('Final-corridor combat not verified: '+combat['outcome'])
            s.transition('jogo');continue
        marker=house_candidate(frame,f);detour=None;heading='down';detour_before=None
        if marker:
            house={'frame':f['frame'],**marker};s.exit_house_evidence=house
            # The end-of-stage house offers the same observed interaction
            # glyph as dialogue. Walking into it is not the exit operation.
            if math.dist(marker['point'],f['player'])<200 and InteractionVision(s.root).affordance(frame) and not InteractionVision.dialogue(frame):
                row=s.pulse(Action('interact',{'ms':100},'Activate the observed final-corridor house exit interaction'))
                context.update(controls_issued=True,exit_interaction_issued=True,interaction_pre_frame=f['frame'],interaction_after_frame=s.last_features['frame'],movement_trace=actions,exit_interaction=row['metrics'])
                s.memory.remember('working','v3_exit_attempt',s.scope,{'run_id':s.run_id,'exit_landmark':house,'exit_context':context,'stage_complete':False},Provenance(f['frame'],method='verified_current_entry_objectives_and_house_marker_then_single_observed_exit_interaction'),.95,'uncertain',dedupe='v3:pending-exit:'+context['entry_token'])
                result=verify_exit_result(s,runtime,bot,house,context)
                if result:result['exit_actions']=actions;return result
                raise RuntimeError('Observed house exit interaction lacks two independent completion observations')
            duration=min(2000,max(100,(marker['point'][1]-f['player'][1]+60)/.44))
        else:
            objects=s.lantern_vision.detect(frame,f['player'],holding=bool(s.held_object_kind));ground=[o for o in objects if o['kind']=='portable_brazier']
            horizon=visible_floor_horizon(frame,f,'down',extra_obstacles=ground,clearance_pixels=28 if ground else 20)
            if horizon:duration=horizon['duration_ms']
            else:
                if actions:
                    _,_,detour_before,_=s.map_state('v3-exit-detour-before-map');s.transition('jogo');frame,f=s.capture('v3-exit-detour-preflight')
                    if s.preflight_enemy(f):raise RuntimeError('Encounter interrupts exit detour')
                else:detour_before=list(arrival)
                objects=s.lantern_vision.detect(frame,f['player'],holding=bool(s.held_object_kind));detour=visible_exit_detour(frame,f,objects)
                if not detour:raise RuntimeError('No observed forward floor or house exit; backward exploration withheld')
                heading=detour['direction'];duration=detour['duration_ms']
        s.prepare_continuous('final_corridor_exit_forward',{'direction':heading,'duration_ms':duration,'exit_landmark':house,'visible_detour':detour,'route':'guide final southern corridor; current floor/marker observed'})
        observer=LiveObserver(s).start();gate=ThreatGate();missing=0;last=-1
        def policy(snapshot):
            nonlocal missing,last,house
            current=snapshot['features']
            if current['scene']!='jogo':return 'screen_changed'
            if current['health'] is not None and current['health']<.25:return 'low_health'
            if gate.update(snapshot):return 'enemy_detected'
            candidate=house_candidate(snapshot['frame'],current)
            if candidate:
                house={'frame':current['frame'],**candidate};s.exit_house_evidence=house
                if not marker and candidate['point'][1]-current['player'][1]<90:return 'exit_marker_approach'
            if snapshot['sequence']!=last:last=snapshot['sequence'];missing=0 if current.get('player') else missing+1
            if missing>=2:return 'actor_lost'
        before_image=frame
        try:control=s.controls.move_hold(heading,duration,monitor=lambda:observer.reason(policy))
        finally:s.backend.release_all();observation_report=observer.close()
        frame,after=s.capture_live('v3-exit-forward-after');row={'control':control,'observations':observation_report,'before_frame':f['frame'],'after_frame':after['frame'],'exit_landmark':house,'visible_detour':detour};actions.append(row);context['controls_issued']=True;context['movement_trace']=actions
        if after['scene']!='jogo' or house and not after.get('player'):
            result=verify_exit_result(s,runtime,bot,house,context)
            if result:s.verify_continuous(result,True);result['exit_actions']=actions;return result
        s.verify_continuous({'control_outcome':control['outcome'],'after_frame':after['frame'],'stage_complete':False},False)
        if control['outcome'] in ('low_health','perception_stale','perception_unavailable'):raise RuntimeError('Exit forward interrupted: '+control['outcome'])
        if control['outcome']=='enemy_detected':continue
        if detour and after['scene']=='jogo':
            _,_,position,checkpoint=s.map_state('v3-exit-detour-after-map');delta=[position[i]-detour_before[i] for i in (0,1)];progress=float(sum(delta[i]*heading[i] for i in (0,1)));revisited=any(math.dist(position,old)<=2 for old in detour_positions)
            proof={'verified':bool(progress>2 and not revisited),'before_reference':detour_before,'after_reference':position,'directional_progress_reference_pixels':progress,'map_frame':checkpoint['frame'],'goal_reached':False,'route':detour};row['detour_check']=proof
            s.memory.remember('episodic','v3_exit_detour',s.scope,{'run_id':s.run_id,**proof},Provenance(checkpoint['frame'],method='visible_floor_flank_with_unchanged_clearance_then_independent_map_displacement'),.9,'verified' if proof['verified'] else 'uncertain')
            if not proof['verified']:raise RuntimeError('Exit detour did not reach a new map position in the planned direction')
            detour_positions.append(list(position));last_map_position=list(position);s.transition('jogo')
        elif after['scene']=='jogo' and control['outcome']=='duration_elapsed':
            motion=SpatialVision.motion(before_image,frame,f.get('player'),after.get('player'));row['motion']=motion
            if motion['confidence']>=.25 and motion['effective_dy']<8:
                _,_,position,checkpoint=s.map_state('v3-exit-forward-stall-check');progress=position[1]-last_map_position[1];row['map_stall_check']={'before':last_map_position,'after':position,'forward_progress_reference_pixels':progress,'frame':checkpoint['frame']};last_map_position=list(position)
                if progress<=2:
                    s.memory.remember('episodic','v3_exit_stall',s.scope,{'run_id':s.run_id,'stagnancy_verified':True,'check':row['map_stall_check'],'motion':motion,'control':control},Provenance(checkpoint['frame'],method='visual_stall_then_independent_map_nonprogress'),.9,'verified')
                    # A flank can meet the narrowing corridor even when wall
                    # shading resembles floor. Replan once on the independent
                    # map target at the current height, with live floor checks.
                    if recentered or abs(position[0]-425.5)<=5:raise RuntimeError('Exit forward segment did not progress in the independent map')
                    recentered=True;recovery=recenter_exit_after_stall(s,position)
                    row['stall_recovery']=recovery
                    if not recovery.get('verified'):raise RuntimeError('Exit lateral recovery lacks a verified map arrival')
                    last_map_position=list(recovery['after']);detour_positions.append(last_map_position)
                    s.memory.remember('episodic','v3_exit_stall_recovery',s.scope,{'run_id':s.run_id,'verified':True,'stagnancy_check':row['map_stall_check'],'route':recovery,'stage_complete':False},Provenance(recovery['after_frame'],method='once_only_map_targeted_visible_lateral_recovery_after_independent_stall'),.95,'verified')
                s.transition('jogo')
    raise RuntimeError('Observed final-corridor exit action budget exhausted')
