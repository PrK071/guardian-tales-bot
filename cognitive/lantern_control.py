"""Image-grounded Passage 1 brazier experiment; no stage-clear verdict here."""
import json,math,time
import cv2
import numpy as np
from .contracts import Action,Provenance
from .map_navigation import PauseMap
from .puzzle_control import BombRockController,DIRECTIONS,direction
from .spatial import SpatialVision

class LanternController:
    def pickup_hand(self,frame):
        from .stage_v2 import InteractionVision
        template=cv2.imread(str(self.s.root/'assets/v3/pickup_hand.png'))
        if template is None:return False
        mask=cv2.inRange(template,(205,205,205),(255,255,255))
        return float(cv2.matchTemplate(InteractionVision.mask(frame),mask,cv2.TM_CCOEFF_NORMED)[0,0])>.92
    def pickup_candidate(self,frame,f,tracked=None):
        if not self.pickup_hand(frame):return None
        bubble=cv2.imread(str(self.s.root/'assets/v3/pickup_object_bubble.png'))
        found=self.s.lantern_vision.matches(frame,bubble,.90,region=[320,100,1080,670],limit=1)
        if not found:return None
        x,y,w,h=found[0]['bbox'];box=[x-18,y+70,110,106]
        if math.dist(f['player'],self.foot({'bbox':box}))>180:return None
        # The current pickup bubble identifies the offered ground object even
        # when its animated flame defeats the generic unlit appearance.
        mask=self.s.lantern_vision.fire_mask(frame);bx,by,bw,bh=box
        burning=np.count_nonzero(mask[by:by+bh,bx:bx+bw])>=450
        tracked_match=bool(tracked and tracked.get('motion_confidence',0)>=.25 and time.time()-tracked.get('at',0)<3 and math.dist(self.foot(tracked),self.foot({'bbox':box}))<30)
        if not burning and not tracked_match:return None
        return {'kind':'portable_brazier','bbox':box,'confidence':found[0]['confidence'],'method':'current_pickup_hand_and_bubble_on_burning_brazier' if burning else 'current_pickup_hand_and_bubble_with_tracked_brazier_occlusion','tracked_source_frame':tracked.get('source_frame') if tracked_match else None}
    def __init__(self,session,seconds=180):
        if session.scope!='world:1:passage:1':raise RuntimeError('Unsupported lantern scope')
        self.s=session;self.deadline=time.monotonic()+seconds;self.events=[]
    def check(self):
        self.s.check_cancel()
        if time.monotonic()>self.deadline:raise RuntimeError('Lantern experiment time budget exhausted')
    def event(self,phase,**data):
        row={'at':time.time(),'phase':phase,**data};self.events.append(row)
        self.s.memory.remember('episodic','v2_lantern_step',self.s.scope,{'run_id':self.s.run_id,**row},Provenance('v2:lantern_control',method='current_images_and_observed_map_pose'),.85,'verified' if data.get('verified') else 'uncertain')
        with (self.s.folder/'lantern.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(json.dumps(row,ensure_ascii=False),flush=True)
    def observe(self,label):
        self.check();frame,f=self.s.capture(label)
        if f['scene']!='jogo' or not f.get('player'):raise RuntimeError('Lantern observation requires visible actor and gameplay HUD')
        if f.get('combat_present',f.get('enemy_count')):
            if not hasattr(self.s,'preflight_enemy') or self.s.preflight_enemy(f):raise RuntimeError('Combat interrupts lantern experiment')
            frame,f=self.s.last_frame,self.s.last_features
        if f.get('health') is not None and f['health']<.30:raise RuntimeError('Insufficient health for lantern experiment')
        return frame,f
    @staticmethod
    def objects(f,kind):return [o for o in f.get('puzzle_objects',[]) if o['kind']==kind and (kind!='standing_lantern_lit' or o.get('method')=='floor_lantern_pedestal_with_current_fire')]
    @staticmethod
    def foot(obj):
        x,y,w,h=obj['bbox'];return [x+w/2,y+h-10]
    def go_to_vantage(self,kind,max_steps=14):
        """Return to a past actor pose, then demand a fresh object observation."""
        if not self.s.map_anchor:raise RuntimeError('Object relocation requires validated map reference')
        self.s.transition('pausa');frame,_=self.s.capture('lantern-vantage-map');state=PauseMap().parse(frame);alignment=self.s.map_anchor.locate(state)
        if not alignment:raise RuntimeError('Cannot align current map to an object sighting')
        actor=self.s.map_anchor.project(state['player'],alignment)
        memories=self.s.memory.retrieve(self.s.scope,kind='v3_stage_landmark',include_global=False,limit=10)+self.s.memory.retrieve(self.s.scope,kind='v2_object_vantage',include_global=False,limit=50)
        candidates=[]
        for m in memories:
            if m['validation']!='verified' or m['content'].get('anchor_id')!=self.s.map_anchor.identity:continue
            if kind=='standing_lantern_lit':
                path=(self.s.root/m['content']['frame']).resolve()
                if not path.is_relative_to(self.s.root.resolve()):continue
                old=cv2.imread(str(path))
                if old is not None and self.objects({'puzzle_objects':self.s.lantern_vision.detect(old)},kind):candidates.append(m)
            elif any(o['kind']==kind for o in m['content'].get('objects',[])):candidates.append(m)
        if not candidates:raise RuntimeError('No observed actor vantage for '+kind)
        if kind=='standing_lantern_lit':
            sources=[m for m in candidates if m['content'].get('label')=='fixed_ignition_source']
            if sources:candidates=sources
        chosen=min(candidates,key=lambda m:math.dist(actor,m['content']['actor_reference']))
        target=chosen['content']['actor_reference'];self.event('vantage_selected',verified=False,kind=kind,memory_id=chosen['id'],actor_reference=target)
        for _ in range(max_steps):
            self.check();self.s.transition('jogo');frame,f=self.observe('lantern-vantage-observe')
            if self.objects(f,kind):return frame,f
            self.s.transition('pausa');frame,_=self.s.capture('lantern-vantage-planning');state=PauseMap().parse(frame);alignment=self.s.map_anchor.locate(state)
            if not alignment:raise RuntimeError('Object vantage map alignment lost')
            actor=self.s.map_anchor.project(state['player'],alignment)
            if math.dist(actor,target)<10:raise RuntimeError('Reached recorded actor pose but object is not currently visible')
            raw=[(target[i]-alignment['source_origin'][i])*alignment['scale']+alignment['top_left'][i] for i in range(2)]
            result=self.s.navigate_once(raw,allow_combat=False,allow_interaction=False)
            self.event('vantage_move',verified=result['metrics']['verified'],plan=result['plan'],map_motion=result['metrics'].get('aligned_map_motion'))
        raise RuntimeError('Object vantage movement budget exhausted')
    def approach(self,kind,reach=110,max_steps=14):
        self.s.transition('jogo');frame,f=self.observe('lantern-find-object')
        if kind=='portable_brazier' and (candidate:=self.pickup_candidate(frame,f)):return frame,f,candidate
        if not self.objects(f,kind):frame,f=self.go_to_vantage(kind)
        unchanged=0;tracked=None;faced=False
        for _ in range(max_steps):
            self.check()
            if kind=='portable_brazier' and (candidate:=self.pickup_candidate(frame,f,tracked)):return frame,f,candidate
            objects=self.objects(f,kind)
            if not objects:raise RuntimeError('Observed '+kind+' lost during approach')
            obj=min(objects,key=lambda o:math.dist(f['player'],self.foot(o)));target=self.foot(obj);distance=math.dist(f['player'],target)
            if kind=='standing_lantern_lit' and obj.get('fire_center') and self.s.held_object_kind=='brazier':
                carried=self.s.lantern_vision.held_match(frame,f['player'])
                if not carried:raise RuntimeError('Carried brazier absent while aligning to the fire source')
                hx,hy,hw,hh=carried['bbox'];wood=[hx+hw/2,hy+hh/2]
                target=[obj['fire_center'][i]-(wood[i]-f['player'][i]) for i in range(2)];distance=math.dist(f['player'],target);reach=min(reach,35)
            if distance<reach and kind!='portable_brazier':return frame,f,obj
            if kind=='portable_brazier' and distance<180:
                from .stage_v2 import InteractionVision
                neutral=cv2.imread(str(self.s.root/'data/v2/v2_calibration_45124c972be4410b/0048-after-jogo.jpg'))
                if neutral is not None and not InteractionVision(self.s.root).affordance(frame):
                    change=float(np.mean(InteractionVision.mask(frame)!=InteractionVision.mask(neutral)))
                    if change>.12 and self.pickup_hand(frame) and not InteractionVision.dialogue(frame):return frame,f,obj
            facing_only=False
            try:heading,ms=BombRockController.local_approach(frame,f,target)
            except RuntimeError as exc:
                if kind!='portable_brazier' or distance>=reach or faced or str(exc)!='No direct local segment with observed player clearance':raise
                # At a wall, the feet can be visually occluded although the
                # adjacent bowl is seen. Face it once; pickup still requires
                # a new hand/bubble observation and the transfer verifier.
                heading,ms=direction(target[0]-f['player'][0],target[1]-f['player'][1]),80;faced=True;facing_only=True
            row=self.s.pulse(Action('move',{'direction':heading,'ms':ms},'Approach observed '+kind));motion=row['metrics']['motion'];vx,vy=DIRECTIONS[heading]
            if kind=='portable_brazier':
                x,y,w,h=obj['bbox'];tracked={'bbox':[x+motion['background_dx'],y+motion['background_dy'],w,h],'source_frame':f['frame'],'motion_confidence':motion['confidence'],'at':time.time()}
            progress=motion['effective_dx']*vx+motion['effective_dy']*vy;verified=motion['confidence']>=.25 and progress>8
            self.event('approach_'+kind,verified=verified,direction=heading,progress=progress,distance_before=distance,facing_only=facing_only)
            unchanged=0 if verified else unchanged+1
            if unchanged>=2:raise RuntimeError('Lantern approach stalled twice; no repeated blind movement')
            frame,f=self.observe('lantern-approach-result')
        raise RuntimeError('Lantern approach action budget exhausted')
    def pickup(self):
        from .stage_v2 import InteractionVision
        frame,f,obj=self.approach('portable_brazier');controls=InteractionVision(self.s.root)
        neutral=cv2.imread(str(self.s.root/'data/v2/v2_calibration_45124c972be4410b/0048-after-jogo.jpg'))
        if neutral is None:raise RuntimeError('Neutral interact appearance unavailable')
        before_glyph=controls.mask(frame);change=float(np.mean(before_glyph!=controls.mask(neutral)))
        self.event('pickup_affordance',verified=False,glyph_change_from_neutral=change,object=obj,player=f['player'],frame=f['frame'])
        if controls.affordance(frame) or change<.12 or not self.pickup_hand(frame):raise RuntimeError('Brazier pickup affordance not established; input withheld')
        before=frame.copy();before_player=f['player'];pickup_action=self.s.pulse(Action('interact',{'ms':100},'Pick up the observed portable brazier'))
        time.sleep(.35);self.check();after,af=self.s.capture('lantern-pickup-result')
        # The newly held bowl can occlude the raw helmet detector. Establish
        # its pose from the stationary pre-transfer actor before requiring it.
        if af['scene']!='jogo' or af.get('health') is not None and af['health']<.30:raise RuntimeError('Pickup result requires current healthy gameplay')
        if af.get('combat_present',af.get('enemy_count')):raise RuntimeError('Encounter interrupts pickup verification')
        motion=SpatialVision.motion(before,after,before_player,af['player']);dx,dy=motion['background_dx'],motion['background_dy'];x,y,w,h=obj['bbox']
        ground_appearance=before[y:y+h,x:x+w]
        matches=self.s.lantern_vision.matches(after,ground_appearance,.65,region=[max(0,int(x+dx-20)),max(150,int(y+dy-20)),w+40,h+40],limit=1)
        ground_score=matches[0]['confidence'] if matches else 0
        estimated=[before_player[0]+dx,before_player[1]+dy]
        held=self.s.lantern_vision.held_match(after,estimated);glyph_change=float(np.mean(before_glyph!=controls.mask(after)))
        verified=bool(motion['confidence']>=.25 and ground_score<.75 and held and held['confidence']>=.70 and glyph_change>.10 and not controls.dialogue(after))
        self.event('pickup_transfer',verified=verified,ground_score=ground_score,held_match=held,glyph_change=glyph_change,motion=motion,frame=af['frame'])
        if not verified:raise RuntimeError('Brazier transfer not verified; no throw or repeated pickup')
        self.s.held_object_kind='brazier'
        hx,hy,hw,hh=held['bbox']
        calibration=self.s.memory.retrieve(self.s.scope,kind='v3_carried_pose_calibration',include_global=False,limit=1)
        if calibration and calibration[0]['validation']=='verified':
            offset=calibration[0]['content']['held_pose_offset'];calibrated=[hx+hw/2+offset[0]*hw,hy+offset[1]*hh]
            if math.dist(estimated,calibrated)>45:raise RuntimeError('Current pickup pose disagrees with the verified carried-object calibration')
            estimated=calibrated
        self.s.held_pose_offset=[(estimated[0]-hx-hw/2)/hw,(estimated[1]-hy)/hh];self.s.held_actor=estimated;self.s.vision.last_player=tuple(estimated);af['player']=estimated
        # Move away from the original ground position and require the reduced
        # brazier to stay above the actor, rather than counting proximity alone.
        away=direction(before_player[0]-self.foot(obj)[0],before_player[1]-self.foot(obj)[1]);vx,vy=DIRECTIONS[away]
        target=[af['player'][0]+vx*90,af['player'][1]+vy*90]
        heading,ms=BombRockController.local_approach(after,af,target)
        row=self.s.pulse(Action('move',{'direction':heading,'ms':ms},'Verify the picked brazier follows the actor'))
        after,af=self.observe('lantern-held-follow');held=self.s.lantern_vision.held_match(after,af['player'])
        verified=bool(row['metrics']['motion']['moved'] and held and held['confidence']>=.70)
        result={'verified':verified,'held_match':held,'frame':af['frame'],'stage_complete':False}
        self.event('held_follow',**result)
        if not verified:raise RuntimeError('Held brazier did not remain visually confirmed after movement')
        pickup_action['metrics'].update(verified=True,lantern_pickup_evidence=result)
        if pickup_action['metrics'].get('operation_id'):
            self.s.memory.operation(pickup_action['metrics']['operation_id'],'observed',self.s.observation(af).id,pickup_action['metrics'])
        self.s.memory.remember('working','v2_held_brazier',self.s.scope,{'run_id':self.s.run_id,'held_pose_offset':self.s.held_pose_offset,**result},Provenance(af['frame'],method='ground_transfer_then_actor_follow'),.9,'verified',dedupe='v2:held-brazier:'+self.s.scope)
        return result
    def restore_held(self):
        """Reconcile a new session with the actual verified throw glyph."""
        from .stage_v2 import InteractionVision
        memories=self.s.memory.retrieve(self.s.scope,kind='v2_held_brazier',include_global=False,limit=1)
        if not memories or memories[0]['validation']!='verified':raise RuntimeError('No verified brazier pickup to reconcile')
        reference_path=(self.s.root/memories[0]['content']['frame']).resolve()
        if not reference_path.is_relative_to(self.s.root.resolve()):raise RuntimeError('Held evidence path outside project')
        reference=cv2.imread(str(reference_path))
        if reference is None:raise RuntimeError('Verified held appearance unavailable')
        self.s.transition('jogo');self.check();frame,f=self.s.capture('lantern-held-reconcile')
        if f['scene']!='jogo' or f.get('health') is not None and f['health']<.30:raise RuntimeError('Held reconciliation requires current healthy gameplay')
        content=memories[0]['content'];offset=content.get('held_pose_offset');seed=f['player']
        if offset and content.get('held_match'):
            hx,hy,hw,hh=content['held_match']['bbox'];seed=[hx+hw/2+offset[0]*hw,hy+offset[1]*hh]
        held=self.s.lantern_vision.held_match(frame,seed)
        if held and offset and not self.s.lantern_vision.carried_actor_visible(frame,held,offset):held=None
        score=float(cv2.matchTemplate(InteractionVision.mask(frame),InteractionVision.mask(reference),cv2.TM_CCOEFF_NORMED)[0,0])
        if not held or held['confidence']<.70 or score<.92:raise RuntimeError('Current held object/throw glyph differs from verified pickup')
        self.s.held_object_kind='brazier';self.event('held_reconciled',verified=True,held_match=held,glyph_score=score,frame=f['frame'])
        if memories[0]['content'].get('held_pose_offset'):
            self.s.held_pose_offset=memories[0]['content']['held_pose_offset'];hx,hy,hw,hh=held['bbox'];dx,dy=self.s.held_pose_offset;self.s.held_actor=[hx+hw/2+dx*hw,hy+dy*hh];self.s.vision.last_player=tuple(self.s.held_actor);f['player']=self.s.held_actor
        return frame,f
    def ignite(self):
        """Touch a source, then require carried flame away from that source."""
        if self.s.held_object_kind!='brazier':frame,f=self.restore_held()
        else:frame,f=self.observe('lantern-ignition-check')
        recovered=None
        if hasattr(self.s,'map_state') and self.s.lantern_vision.held_fire_pixels(frame,f['player'])>450:
            known=self.s.memory.retrieve(self.s.scope,kind='v3_fixed_fire_source',include_global=False,limit=1)
            if known and known[0]['content'].get('anchor_id')==self.s.map_anchor.identity:
                recovered=known[0];_,_,actor_reference,_=self.s.map_state('v3-ignition-recovery-map')
                self.s.transition('jogo');frame,f=self.s.last_frame,self.s.last_features
                data=recovered['content'];ratio=data['world_pixels_per_reference_pixel']
                source_point=[f['player'][i]+(data['reference_point'][i]-actor_reference[i])*ratio for i in range(2)]
                self.event('occluded_source_recovery',verified=False,source_memory_id=recovered['id'],source_point_estimate=source_point,source_uncertainty_reference_pixels=data['uncertainty_reference_pixels'])
        if recovered is None:
            try:
                frame,f,source=self.approach('standing_lantern_lit',reach=110);source_point=self.foot(source)
            except RuntimeError as exc:
                if str(exc)!='Observed standing_lantern_lit lost during approach' or not hasattr(self.s,'map_state'):raise
                frame,f=self.observe('lantern-source-occluded-after-contact')
                if self.s.lantern_vision.held_fire_pixels(frame,f['player'])<=450:raise exc
                known=self.s.memory.retrieve(self.s.scope,kind='v3_fixed_fire_source',include_global=False,limit=1)
                if not known or known[0]['content'].get('anchor_id')!=self.s.map_anchor.identity:raise exc
                recovered=known[0];_,_,actor_reference,_=self.s.map_state('v3-contact-source-separation-map')
                self.s.transition('jogo');frame,f=self.s.last_frame,self.s.last_features;data=recovered['content'];ratio=data['world_pixels_per_reference_pixel']
                source_point=[f['player'][i]+(data['reference_point'][i]-actor_reference[i])*ratio for i in range(2)]
                self.event('source_occluded_after_observed_ignition',verified=False,source_memory_id=recovered['id'],source_point_estimate=source_point,frame=f['frame'])
        confirmations=0;total_motion=0
        for _ in range(8):
            self.check();player=f['player'];heading=direction(player[0]-source_point[0],player[1]-source_point[1]);vx,vy=DIRECTIONS[heading]
            target=[player[0]+vx*100,player[1]+vy*100]
            heading,ms=BombRockController.local_approach(frame,f,target)
            row=self.s.pulse(Action('move',{'direction':heading,'ms':ms},'Move away from the observed source to test carried fire'))
            motion=row['metrics']['motion'];source_point=[source_point[0]+motion['background_dx'],source_point[1]+motion['background_dy']]
            total_motion+=math.hypot(motion['effective_dx'],motion['effective_dy']) if motion['confidence']>=.25 else 0
            frame,f=self.observe('lantern-carried-fire');pixels=self.s.lantern_vision.held_fire_pixels(frame,f['player'])
            # A nearby standing flame can enter the same overhead ROI. Its
            # tracked fixed base must be separated from the actor as well.
            separated=math.dist(source_point,f['player'])>425 if recovered else abs(source_point[0]-f['player'][0])>125 or math.dist(source_point,f['player'])>275
            verified=bool(pixels>450 and separated and total_motion>65)
            confirmations=confirmations+1 if verified else 0
            self.event('carried_fire_observation',verified=verified,fire_pixels=pixels,source_point=source_point,actor=f['player'],total_motion=total_motion,frame=f['frame'])
            if confirmations>=2:
                result={'verified':True,'confirmations':confirmations,'frame':f['frame'],'stage_complete':False}
                if recovered:
                    _,_,current_reference,map_features=self.s.map_state('v3-ignition-independent-separation')
                    distance=math.dist(current_reference,recovered['content']['reference_point'])*recovered['content']['world_pixels_per_reference_pixel']
                    if distance<425:raise RuntimeError('Map did not independently confirm separation from the estimated fire source')
                    result.update(source_memory_id=recovered['id'],source_separation_world_pixels=distance,map_frame=map_features['frame'])
                    self.s.transition('jogo')
                self.s.memory.remember('working','v2_carried_fire',self.s.scope,{'run_id':self.s.run_id,**result},Provenance(f['frame'],method='two_overhead_fire_observations_away_from_fixed_source'),.9,'verified',dedupe='v2:carried-fire:'+self.s.scope)
                return result
        raise RuntimeError('Carried fire not confirmed away from the standing source')
