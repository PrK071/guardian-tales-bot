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
    if not path.is_relative_to(s.folder.resolve()) or not path.exists() or not arrival or arrival[1]<930 or abs(arrival[0]-425.5)>10:raise RuntimeError('No current-run final-corridor map arrival')
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
    valid_transition=bool(context and context.get('current_entry_verified') and context.get('controls_issued') and house_path and house_path.is_relative_to(s.folder.resolve()) and house_path.exists())
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

def exit_forward(s,runtime,bot,arrival,map_frame,max_actions=10):
    context=verified_exit_context(s,arrival,map_frame)
    s.transition('jogo');house=getattr(s,'exit_house_evidence',None);actions=[]
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
        marker=house_candidate(frame,f)
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
            horizon=visible_floor_horizon(frame,f,'down')
            if not horizon:raise RuntimeError('No observed forward floor or house exit; backward exploration withheld')
            duration=horizon['duration_ms']
        s.prepare_continuous('final_corridor_exit_forward',{'duration_ms':duration,'exit_landmark':house,'route':'guide final southern corridor; current floor/marker observed'})
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
        try:control=s.controls.move_hold('down',duration,monitor=lambda:observer.reason(policy))
        finally:s.backend.release_all();observation_report=observer.close()
        frame,after=s.capture_live('v3-exit-forward-after');row={'control':control,'observations':observation_report,'before_frame':f['frame'],'after_frame':after['frame'],'exit_landmark':house};actions.append(row);context['controls_issued']=True;context['movement_trace']=actions
        if after['scene']!='jogo' or house and not after.get('player'):
            result=verify_exit_result(s,runtime,bot,house,context)
            if result:s.verify_continuous(result,True);result['exit_actions']=actions;return result
        s.verify_continuous({'control_outcome':control['outcome'],'after_frame':after['frame'],'stage_complete':False},False)
        if control['outcome'] in ('low_health','perception_stale','perception_unavailable'):raise RuntimeError('Exit forward interrupted: '+control['outcome'])
    raise RuntimeError('Observed final-corridor exit action budget exhausted')
