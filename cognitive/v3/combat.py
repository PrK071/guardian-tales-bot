"""Local encounter state machine. Qwen is never called for individual attacks."""
import math,time
import cv2
import numpy as np
from ..contracts import Provenance
from ..spatial import SpatialVision
from .continuous import VECTORS
from .observation import LiveObserver
from .hazards import solid_spike

def combat_present(features):return features.get('combat_present',bool(features['enemy_count']))

def nearest_enemy(features):
    player=features.get('player')
    if not player:return None,None
    enemies=[e for e in features.get('entities',[]) if e['kind']=='enemy']
    if not enemies:return None,None
    def point(e):
        x,y,w,h=e['bbox'];return [x+w/2,y+h-10]
    enemy=min(enemies,key=lambda e:math.dist(player,point(e)))
    return point(enemy),math.dist(player,point(enemy))

def retreat_vector(frame,features):
    player=features.get('player');target,_=nearest_enemy(features)
    hazards=[e for e in features.get('entities',[]) if e['kind']=='hazard' and solid_spike(frame,e)]
    if player and hazards:
        hazard=min(hazards,key=lambda e:math.dist(player,[e['bbox'][0]+e['bbox'][2]/2,e['bbox'][1]+e['bbox'][3]-20]))
        point=[hazard['bbox'][0]+hazard['bbox'][2]/2,hazard['bbox'][1]+hazard['bbox'][3]-20]
        if math.dist(player,point)<180:target=point
    if frame is None or not player or not target:return None
    floor=SpatialVision().entities(frame)['floor_mask'];px,py=map(int,player);cv2.circle(floor,(px,py),35,255,-1)
    for e in features.get('entities',[]):
        if e['kind'] not in ('hazard','rock_obstacle_candidate'):continue
        x,y,w,h=e['bbox'];floor[max(0,y-25):min(900,y+h+25),max(0,x-25):min(1600,x+w+25)]=0
    clearance=cv2.distanceTransform(floor,cv2.DIST_L2,5);candidates=[]
    for vector in VECTORS.values():
        length=math.hypot(*vector);vx,vy=vector[0]/length,vector[1]/length
        points=[(round(px+vx*d),round(py+vy*d)) for d in (20,40,60,80)]
        if not all(0<=x<1600 and 0<=y<900 and clearance[y,x]>18 for x,y in points):continue
        score=math.dist(points[-1],target)-math.dist(player,target)
        if score>20:candidates.append((score,[vx,vy]))
    return max(candidates,key=lambda row:row[0])[1] if candidates else None

class CombatController:
    def __init__(self,session,controls,skill_ready=None,prior_enemy_evidence=None):
        self.prior_enemy_evidence=prior_enemy_evidence
        self.s=session;self.controls=controls;self.skill_ready=skill_ready;self.events=[];self.observed=bool(prior_enemy_evidence and prior_enemy_evidence.get('scene')=='jogo' and combat_present(prior_enemy_evidence) and 0<=time.time()-prior_enemy_evidence.get('at',0)<10);self.clear_frames=[];self.clear_sequences=set();self.skill_attempts=0;self.reorientations=0;self.evasions=0
    def state(self,name,**data):
        row={'at':time.time(),'state':name,**data};self.events.append(row)
        self.s.memory.remember('episodic','v3_combat_state',self.s.scope,{'run_id':self.s.run_id,**row},Provenance('v3:combat',method='local_observation_state_machine'),.85,'verified' if data.get('observed') else 'uncertain')
    def run(self,seconds=60):
        self.s.check_cancel()
        if self.s.last_features['scene']!='jogo':self.s.transition('jogo')
        if time.time()-self.s.last_features.get('at',0)>.5:self.s.capture('v3-combat-initial')
        observer=LiveObserver(self.s).start();deadline=time.monotonic()+seconds;outcome='combat_budget_exhausted';last_sequence=-1;missing=0;last_skill=0;start_actions=len(self.controls.actions);raw_confirmation=None;target_missing=0
        self.state('ENEMY_DETECTED',observed=self.observed or bool(self.s.last_features['enemy_count']),frame=self.s.last_features['frame'],prior_frame=(self.prior_enemy_evidence or {}).get('frame'))
        try:
            while time.monotonic()<deadline:
                self.s.check_cancel();snap=observer.snapshot();f=snap['features']
                if snap['error'] or snap['age_seconds']>observer.stale_seconds:outcome='perception_unavailable';break
                if f['scene']!='jogo':outcome='screen_changed';break
                if snap['sequence']==last_sequence:time.sleep(.01);continue
                last_sequence=snap['sequence']
                if not combat_present(f):
                    if not self.observed:outcome='no_observed_enemy';break
                    if snap['sequence'] not in self.clear_sequences:self.clear_sequences.add(snap['sequence']);self.clear_frames.append(f['frame'])
                    if len(self.clear_frames)>=3:
                        if getattr(getattr(self.s,'backend',None),'video',None):
                            self.controls.backend.release_all();observer.close();_,raw=self.s.capture('v3-combat-raw-clear-confirmation');raw_confirmation=raw['frame']
                            if raw['scene']!='jogo':outcome='screen_changed';break
                            if combat_present(raw):
                                self.state('RECOVER',observed=True,reason='raw_enemy_still_present',frame=raw['frame']);self.clear_frames=[];self.clear_sequences=set();observer=LiveObserver(self.s).start();last_sequence=-1;continue
                        outcome='visible_combat_ended';break
                    continue
                self.observed=True;self.clear_frames=[];self.clear_sequences=set()
                if f['health'] is not None and f['health']<.20:
                    self.state('RETREAT',observed=True,health=f['health'],frame=f['frame']);vector=retreat_vector(snap['frame'],f)
                    if vector:self.controls.move_hold(vector,180);outcome='bounded_retreat_attempted'
                    else:outcome='retreat_unavailable'
                    break
                if not f.get('player'):
                    missing+=1;self.state('RECOVER',observed=True,reason='actor_temporarily_missing',frame=f['frame'])
                    if missing>=3:outcome='actor_unavailable';break
                    continue
                missing=0;target,distance=nearest_enemy(f)
                if target is None:
                    target_missing+=1
                    if target_missing>=20:outcome='enemy_position_unavailable';break
                    continue
                target_missing=0
                if distance>145:
                    self.state('APPROACH',observed=True,distance=distance,frame=f['frame'])
                    vector=[target[0]-f['player'][0],target[1]-f['player'][1]]
                    def approach(snap):
                        current=snap['features']
                        if current['scene']!='jogo':return 'screen_changed'
                        if current['health'] is not None and current['health']<.20:return 'low_health'
                        if not current.get('player'):return 'actor_lost'
                        if not combat_present(current):return 'enemy_changed'
                        _,d=nearest_enemy(current)
                        if d is not None and d<140:return 'in_range'
                        hazards=[e for e in current.get('entities',[]) if e['kind']=='hazard']
                        if current.get('hazard_count') and (not hazards or any(solid_spike(snap['frame'],e) for e in hazards)):return 'observed_hazard'
                    duration=min(2000,max(100,(distance-110)/.44))
                    result=self.controls.move_hold(vector,duration,monitor=lambda:observer.reason(approach))
                    if result['outcome'].startswith('perception_') or result['outcome']=='screen_changed':outcome=result['outcome'];break
                    if result['outcome']=='observed_hazard':outcome='hazard_blocks_approach';break
                    continue
                self.state('ENGAGE',observed=True,frame=f['frame']);self.state('CONTINUOUS_ATTACK',frame=f['frame'])
                previous_sequence=-1;absent=[];last_area=f['focused_enemy_hp']['red_area'] if f.get('focused_enemy_hp') else f['enemy_red_area'];last_effect=time.monotonic()
                def attack(snap):
                    nonlocal previous_sequence,absent,last_area,last_effect,last_skill
                    current=snap['features']
                    if current['scene']!='jogo':return 'screen_changed'
                    if current['health'] is not None and current['health']<.20:return 'low_health'
                    if snap['sequence']==previous_sequence:return None
                    previous_sequence=snap['sequence']
                    if not combat_present(current):
                        # Stop the offensive hold at the first lost target, then
                        # verify three distinct frames without lunging forward.
                        self.clear_frames=[current['frame']];self.clear_sequences={snap['sequence']}
                        return 'enemy_not_visible'
                    absent=[]
                    if not current.get('player'):return 'actor_lost'
                    for entity in current.get('entities',[]):
                        if entity['kind']=='hazard' and solid_spike(snap['frame'],entity):
                            x,y,w,h=entity['bbox']
                            if math.dist(current['player'],[x+w/2,y+h-20])<180:return 'evade_hazard'
                    _,d=nearest_enemy(current)
                    if d is not None and d>220:return 'out_of_range'
                    area=current['focused_enemy_hp']['red_area'] if current.get('focused_enemy_hp') else current['enemy_red_area']
                    if area<last_area-20:last_effect=time.monotonic()
                    last_area=area
                    if self.skill_ready and time.monotonic()-last_skill>1 and self.skill_ready(snap['frame'],current):
                        self.controls.use_skill();self.skill_attempts+=1;last_skill=time.monotonic();self.state('SKILL_WHEN_READY',observed=True,frame=current['frame'])
                    if time.monotonic()-last_effect>3:return 'attack_stalled'
                result=self.controls.attack_hold(min(30000,max(40,(deadline-time.monotonic())*1000)),monitor=lambda:observer.reason(attack))
                reason=result['outcome'];self.state('VERIFY_COMBAT_STATE',observed=True,reason=reason,frame=self.clear_frames[-1] if reason=='enemy_not_visible' and self.clear_frames else self.s.last_features['frame'])
                if reason=='visible_combat_ended':outcome=reason;break
                if reason.startswith('perception_') or reason=='screen_changed':outcome=reason;break
                if reason=='evade_hazard':
                    current=observer.snapshot();vector=retreat_vector(current['frame'],current['features'])
                    if not vector or self.evasions>=2:outcome='evade_unavailable';break
                    self.state('EVASION',observed=True,frame=current['features']['frame']);self.controls.move_hold(vector,180);self.evasions+=1
                if reason=='attack_stalled':
                    if self.reorientations>=2:outcome='combat_stalled';break
                    current=observer.snapshot()['features'];target,_=nearest_enemy(current)
                    if target and current.get('player') and not current.get('hazard_count'):
                        self.state('ORIENT',observed=True,frame=current['frame']);self.controls.move_hold([target[0]-current['player'][0],target[1]-current['player'][1]],80);self.reorientations+=1
        finally:
            self.controls.backend.release_all();observation_report=observer.close()
        result={'outcome':outcome,'visible_combat_ended':outcome=='visible_combat_ended' and self.observed and len(self.clear_frames)>=3,'clear_frames':self.clear_frames,'raw_confirmation':raw_confirmation,'states':self.events,'continuous_actions':self.controls.actions[start_actions:],'skill_attempts':self.skill_attempts,'reorientations':self.reorientations,'evasions':self.evasions,'observations':observation_report,'stage_complete':False}
        self.state('FINISH',observed=True,outcome=outcome)
        self.s.memory.remember('episodic','v3_combat',self.s.scope,{'run_id':self.s.run_id,**result},Provenance('v3:combat',method='continuous_hold_and_three_distinct_enemy_absence_frames'),.9,'verified' if result['visible_combat_ended'] else 'uncertain')
        return result
