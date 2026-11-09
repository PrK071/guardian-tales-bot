"""Bounded, visual bomb/rock experiment for the observed Passage 1 only.

The guide is a hypothesis. Pickup needs an observed transfer of the cyan core;
throwing needs that held core; success needs loss of the observed rock pixels.
No result here is a stage-clear verdict.
"""
from __future__ import annotations
import math,time
import cv2
import numpy as np
from .contracts import Action,Provenance
from .map_navigation import PauseMap
from .spatial import SpatialVision

DIRECTIONS={'up':(0,-1),'down':(0,1),'left':(-1,0),'right':(1,0),'up_left':(-.707,-.707),'up_right':(.707,-.707),'down_left':(-.707,.707),'down_right':(.707,.707)}

def direction(dx,dy):
    if abs(dx)>abs(dy)*1.8:return 'right' if dx>0 else 'left'
    if abs(dy)>abs(dx)*1.8:return 'down' if dy>0 else 'up'
    return ('down' if dy>0 else 'up')+'_'+('right' if dx>0 else 'left')

def cyan_mask(frame):return cv2.inRange(cv2.cvtColor(frame,cv2.COLOR_BGR2HSV),(75,105,100),(110,255,255))
def rock_mask(frame):return cv2.inRange(cv2.cvtColor(frame,cv2.COLOR_BGR2HSV),(55,20,80),(72,105,250))
def crop(mask,bbox,shift=(0,0)):
    x,y,w,h=bbox;dx,dy=shift;x=int(round(x+dx));y=int(round(y+dy))
    return mask[max(0,y):min(mask.shape[0],y+h),max(0,x):min(mask.shape[1],x+w)]
def held_pixels(frame,player):
    if not player:return 0
    # Above the helmet; the knight's blue shield near the feet is excluded.
    x,y=player;return int(np.count_nonzero(crop(cyan_mask(frame),[int(x-65),int(y-190),130,105])))
def core_pixels(frame,bbox,shift=(0,0)):return int(np.count_nonzero(crop(cyan_mask(frame),bbox,shift)))
def rock_pixels(frame,bbox,shift=(0,0)):return int(np.count_nonzero(crop(rock_mask(frame),bbox,shift)))

def pickup_evidence(before,after,bomb,before_player,after_player,motion):
    if motion['confidence']<.25:return {'verified':False,'reason':'camera_alignment_uncertain'}
    shift=(motion['background_dx'],motion['background_dy'])
    old=core_pixels(before,bomb);remaining=core_pixels(after,bomb,shift)
    held_before=held_pixels(before,before_player);held_after=held_pixels(after,after_player)
    verified=old>=200 and remaining<old*.35 and held_after-held_before>250
    return {'verified':bool(verified),'plant_core_before':old,'plant_core_after':remaining,'held_before':held_before,'held_after':held_after,'camera_shift':list(shift)}

def removal_evidence(before,after,rock,motion):
    if motion['confidence']<.25:return {'verified':False,'reason':'camera_alignment_uncertain'}
    dx,dy=motion['background_dx'],motion['background_dy'];x,y,w,h=rock;ah,aw=after.shape[:2]
    visible=max(0,min(aw,x+dx+w)-max(0,x+dx))*max(0,min(ah,y+dy+h)-max(0,y+dy))/(w*h)
    if visible<.90:return {'verified':False,'reason':'target_left_visible_frame','visible_fraction':visible}
    old=rock_pixels(before,rock);remaining=rock_pixels(after,rock,(dx,dy))
    reference=np.zeros(before.shape[:2],np.uint8);reference[y:y+h,x:x+w]=rock_mask(before)[y:y+h,x:x+w]
    aligned=cv2.warpAffine(reference,np.float32([[1,0,dx],[0,1,dy]]),(aw,ah),flags=cv2.INTER_NEAREST)>0
    floor=cv2.inRange(cv2.cvtColor(after,cv2.COLOR_BGR2HSV),(0,75,65),(25,225,175))>0
    exposed=float(np.mean(floor[aligned])) if np.any(aligned) else 0
    return {'verified':bool(old>4000 and remaining<old*.25 and exposed>.55),'rock_pixels_before':old,'rock_pixels_after':remaining,'exposed_floor_fraction':exposed,'camera_shift':[dx,dy]}

class BombRockController:
    def __init__(self,session,hypothesis,seconds=45):
        self.session=session;self.hypothesis=hypothesis;self.deadline=time.monotonic()+min(60,max(5,seconds));self.events=[];self.last_direction=None
    def check(self):
        self.session.check_cancel()
        if time.monotonic()>self.deadline:raise RuntimeError('Puzzle time budget exhausted')
    def observe(self,label):
        self.check();frame,features=self.session.capture(label)
        if features['scene']!='jogo':raise RuntimeError('Puzzle requires the observed gameplay HUD')
        if not features.get('player'):raise RuntimeError('Puzzle player position unavailable')
        if features.get('enemy_count'):raise RuntimeError('Combat interrupts the puzzle experiment')
        if features.get('health') is not None and features['health']<.30:raise RuntimeError('Insufficient health for puzzle experiment')
        return frame,features
    @staticmethod
    def candidates(features,kind):return [e for e in features['entities'] if e['kind']==kind and e['confidence']>=.70]
    def event(self,phase,result):
        row={'phase':phase,**result};self.events.append(row)
        self.session.memory.remember('episodic','v2_puzzle_step',self.session.scope,{'run_id':self.session.run_id,'source_memory':self.hypothesis['memory_id'],**row},Provenance('v2:puzzle_control',method='aligned_before_after_pixels'),.8,'verified' if result.get('verified') else 'uncertain')
    @staticmethod
    def local_approach(frame,features,target):
        floor=SpatialVision.floor_mask(frame)
        # The player itself obscures floor. Reconstruct only a small disk at
        # the observed feet; the rest of the route needs visible floor.
        px,py=features['player'];own_sprite_methods=('observed_helmet_template_with_calibrated_foot','observed_partial_helmet_with_calibrated_foot')
        if target[1]<py-60:own_sprite_methods+=('silver_helmet_top_plus_observed_95px_height',)
        verified_helmet=any(e['kind']=='player' and e.get('method') in own_sprite_methods for e in features['entities'])
        radius=55 if features.get('actor_pose_source')=='calibrated_carried_brazier_offset' or verified_helmet else 36
        # A verified carried-object pose also has the follower overlapping its
        # feet. Restore that observed sprite footprint, then re-mask all rocks.
        cv2.circle(floor,(int(px),int(py)),radius,255,-1)
        # The actor (and a carried brazier) obscures its own approach lane.
        # Restore only short rows with observed floor on BOTH flanks, as for
        # the pause-map pin; never flood an unknown wall or the whole sprite.
        for sy in range(max(0,int(py-110)),min(900,int(py+13))):
            lx,rx=int(px-95),int(px+95)
            if 0<=lx<rx<1600 and floor[sy,lx] and floor[sy,rx]:floor[sy,max(0,int(px-80)):min(1600,int(px+81))]=255
        sprite_occlusion=np.zeros_like(floor)
        if verified_helmet:
            # The actor itself occludes the narrow path ahead of its feet.
            # Permit a moderate observation horizon through that known sprite;
            # explicit stones/hazards are re-masked below and stalls still stop.
            x1=max(320,int(px-40));x2=min(1400,int(px+41));y1=max(150,int(py-100));y2=min(820,int(py+12))
            sprite_occlusion[y1:max(y1,int(py-40)),x1:x2]=255
            floor[y1:y2,x1:x2]=255
        for entity in features['entities']:
            if entity['kind']=='friendly_follower' and math.dist([entity['bbox'][0]+entity['bbox'][2]/2,entity['bbox'][1]+entity['bbox'][3]],(px,py))<180:
                x,y,w,h=entity['bbox'];floor[y:y+h,x:x+w]=255;sprite_occlusion[y:y+h,x:x+w]=255
        if features.get('actor_pose_source')=='calibrated_carried_brazier_offset':
            # Reconstruct a verified carried sprite only on scanlines where
            # floor is visible immediately to BOTH sides of its silhouette.
            boxes=[[int(px-42),int(py-105),84,117]]
            if features.get('held_object_bbox'):boxes.append(features['held_object_bbox'])
            for x,y,w,h in boxes:
                left=max(320,x-8);right=min(1399,x+w+8)
                for sy in range(max(150,y),min(820,y+h)):
                    if floor[sy,left] and floor[sy,right]:floor[sy,left:right+1]=255
        for e in features['entities']:
            if e['kind'] not in ('hazard','rock_obstacle_candidate'):continue
            x,y,w,h=e['bbox'];floor[max(0,y):y+h,max(0,x):x+w]=0
        state={'floor':floor,'player':[px,py]}
        path=PauseMap().path(state,target,cell=16,margin=28,reachable_target=True)
        if len(path)<2:raise RuntimeError('No visible approach to the object within player clearance')
        from .v3.segments import clear_line
        clearance=cv2.distanceTransform(floor,cv2.DIST_L2,5)
        # Pull the longest safe eight-direction segment out of the BFS route.
        # A staircase grid path otherwise creates an artificial turn every cell.
        for point in reversed(path[1:]):
            dx,dy=point[0]-px,point[1]-py;heading=direction(dx,dy);vx,vy=DIRECTIONS[heading];length=math.hypot(vx,vy);vx/=length;vy/=length
            distance=max(0,dx*vx+dy*vy);distance=min(distance,1200*.44)
            endpoint=[px+vx*distance,py+vy*distance]
            if distance>=15 and clear_line(clearance,[px,py],endpoint,28,start_escape=True):
                ray=np.zeros_like(floor);cv2.line(ray,(round(px),round(py)),(round(endpoint[0]),round(endpoint[1])),255,1)
                duration=max(80,round(distance/.44*.9))
                if np.any((ray>0)&(sprite_occlusion>0)):duration=min(duration,300)
                return heading,duration
        raise RuntimeError('No direct local segment with observed player clearance')
    def solve(self):
        if self.session.scope!='world:1:passage:1' or self.hypothesis.get('validation')!='hypothesis':raise RuntimeError('Puzzle hypothesis scope/type not supported')
        if self.hypothesis.get('steps')!=['approach_observed_bomb','interact_and_verify_pickup','face_observed_rock','interact_and_verify_obstacle_change']:raise RuntimeError('Unsupported puzzle steps')
        unchanged=0
        for attempt in range(12):
            frame,features=self.observe('puzzle-approach')
            bombs=self.candidates(features,'bomb_candidate');rocks=self.candidates(features,'rock_obstacle_candidate')
            if not bombs or not rocks:raise RuntimeError('Both reported puzzle objects must still be observed')
            player=features['player'];bomb=min(bombs,key=lambda e:math.dist((e['bbox'][0]+e['bbox'][2]/2,e['bbox'][1]+e['bbox'][3]-10),player))
            x,y,w,h=bomb['bbox'];target=[x+w/2,y+h-10]
            if math.dist(player,target)<110:break
            heading,ms=self.local_approach(frame,features,target)
            row=self.session.pulse(Action('move',{'direction':heading,'ms':ms},'Approach the visually observed bomb hypothesis'))
            motion=row['metrics']['motion'];vx,vy=DIRECTIONS[heading];progress=motion['effective_dx']*vx+motion['effective_dy']*vy
            moved=motion['confidence']>=.25 and progress>8
            self.event('approach',{'verified':moved,'direction':heading,'directional_pixels':progress})
            unchanged=0 if moved else unchanged+1
            if unchanged>=2:raise RuntimeError('Puzzle approach had two unverified moves; replan instead of repeating')
            self.last_direction=heading
        else:raise RuntimeError('Puzzle approach action budget exhausted')
        # A nearby flower alone does not prove the button offers pickup. Require
        # a changed interact glyph relative to the recorded boots and reject chat.
        from .stage_v2 import InteractionVision
        controls=InteractionVision(self.session.root)
        reference=cv2.imread(str(self.session.root/'data/v2/v2_calibration_45124c972be4410b/0048-after-jogo.jpg'))
        if reference is None:raise RuntimeError('Observed neutral control reference missing')
        mask=controls.mask(frame);neutral=controls.mask(reference)
        glyph_change=float(np.mean(mask!=neutral))
        if controls.affordance(frame) or glyph_change<.12:raise RuntimeError('Pickup affordance not established; interact command withheld')
        bomb_box=bomb['bbox'];before_player=player.copy();held_before=held_pixels(frame,player)
        self.session.pulse(Action('interact',{'ms':100},'Test the observed pickup affordance'))
        after=self.session.last_frame;features=self.session.last_features
        if controls.dialogue(after):raise RuntimeError('Dialogue appeared instead of a verified pickup')
        motion=SpatialVision.motion(frame,after,before_player,features.get('player'))
        pickup=pickup_evidence(frame,after,bomb_box,before_player,features.get('player'),motion);self.event('pickup',pickup)
        if not pickup['verified']:raise RuntimeError('Pickup not verified; pause without blind throw')
        # A second current image must retain a held object before throwing.
        held_frame,features=self.observe('puzzle-held-confirm')
        if held_pixels(held_frame,features['player'])<held_before+200:raise RuntimeError('Held object absent before throw')
        rocks=self.candidates(features,'rock_obstacle_candidate')
        if not rocks:raise RuntimeError('No current observed rock target for the held bomb')
        player=features['player'];rock=min(rocks,key=lambda e:math.dist((e['bbox'][0]+e['bbox'][2]/2,e['bbox'][1]+e['bbox'][3]/2),player))
        x,y,w,h=rock['bbox'];target=[min(max(player[0],x),x+w),min(max(player[1],y),y+h)]
        if math.dist(player,target)>250:raise RuntimeError('Observed rock is beyond the bounded throw experiment range')
        heading=direction(target[0]-player[0],target[1]-player[1])
        if self.last_direction!=heading:
            self.session.pulse(Action('move',{'direction':heading,'ms':80},'Face the observed rock before throwing'))
        before,features=self.observe('puzzle-before-throw')
        if held_pixels(before,features['player'])<200:raise RuntimeError('Held object expired before throw; no throw claimed')
        rocks=self.candidates(features,'rock_obstacle_candidate')
        if not rocks:raise RuntimeError('Rock target lost before throw')
        rock=min(rocks,key=lambda e:math.dist((e['bbox'][0],e['bbox'][1]),(x,y)))
        rock_box=rock['bbox'];before_player=features['player']
        self.session.pulse(Action('interact',{'ms':100},'Throw the verified held object toward the observed rock'))
        end=min(self.deadline,time.monotonic()+6);confirmations=0;result={'verified':False}
        while time.monotonic()<end:
            after,features=self.observe('puzzle-result')
            motion=SpatialVision.motion(before,after,before_player,features['player'])
            result=removal_evidence(before,after,rock_box,motion)
            confirmations=confirmations+1 if result['verified'] else 0
            if confirmations>=2:
                self.event('rock_removed',result)
                solution={'verified':True,'run_id':self.session.run_id,'source_memory':self.hypothesis['memory_id'],'rock_bbox':rock_box,'result':result,'confirmations':confirmations,'stage_complete':False}
                self.session.memory.remember('semantic','v2_puzzle_solution',self.session.scope,solution,Provenance('v2:puzzle_control',method='two_aligned_rock_removal_observations'),.9,'verified')
                return solution
        self.event('throw_unconfirmed',result)
        raise RuntimeError('Throw sent but rock removal not confirmed; puzzle remains unsolved')
