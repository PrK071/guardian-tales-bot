from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import hashlib,json,math,struct,threading,time
import cv2
import numpy as np
from .contracts import Action,Observation,Provenance,now,uid
from .spatial import SpatialVision
from .lantern_vision import LanternVision

class FastSession:
    """Bounded Android tactical loop, reusing existing ADB and SQLite interfaces."""
    def __init__(self,root,adb,memory,cancel=None,scope='world:1:passage:1',run_id=None,artifact_base='data/v2'):
        self.root=Path(root);self.adb=adb;self.memory=memory;self.cancel=cancel or threading.Event();self.scope=scope
        base=(self.root/artifact_base).resolve()
        if not base.is_relative_to((self.root/'data').resolve()):raise ValueError('Session artifacts must remain inside project data')
        self.run_id=run_id or uid('v2_calibration');self.folder=base/self.run_id;self.folder.mkdir(parents=True,exist_ok=True)
        self.vision=SpatialVision();self.frames=0;self.actions=[];self.last_frame=None;self.last_features=None
        self.lantern_vision=LanternVision(self.root);self.held_object_kind=None
        self.owner=self.run_id;self.start=time.perf_counter();self.local_position=[0.,0.]
        self.goal_id=None;self.task_id=None
        self.failed_edge=None;self.failed_count=0;self.recovery_count=0
        self.interaction_handler=None
        self.world_features=None
        self.kind='calibration_not_autonomous_stage_completion'
        self.map_anchor=None
        self.frame_callback=None;self.last_plan=None;self.last_plan_state=None
        # Safe-stem calibration: 900ms fixed-axis hold moved 53.19 reference
        # pixels, versus roughly 27 for the legacy center-to-edge ramp.
        # V1's ADB.move remains unchanged.
        self.joystick_style='fixed_hold'
        self.deferred_frontiers=[m['content'] for m in self.memory.retrieve(self.scope,kind='v2_frontier_blocked',include_global=False,limit=12) if m['validation']=='verified' and m['content'].get('expires_at',0)>now()]
        self.code_hashes={name:hashlib.sha256((self.root/name).read_bytes()).hexdigest() for name in ('bot.py','config.json','cognitive/spatial.py','cognitive/map_navigation.py','cognitive/map_anchor.py','cognitive/fast_control.py','cognitive/stage_v2.py','cognitive/puzzle_control.py','cognitive/lantern_vision.py','cognitive/lantern_control.py','cognitive/hazard_control.py','assets/v2/portable_brazier.png','assets/v2/standing_lantern_unlit.png','cognitive/contracts.py','cognitive/memory.py','cognitive/perception.py','cognitive/runtime.py','cognitive/planning.py','cognitive/research.py','cognitive/local_model.py')}
        if base.is_relative_to((self.root/'data/v3').resolve()):
            for folder in (self.root/'cognitive/v3',self.root/'evaluations/v3'):
                for path in folder.glob('*.py'):
                    self.code_hashes[path.relative_to(self.root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (self.root/'assets/v3').glob('*.png'):
            self.code_hashes[path.relative_to(self.root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
        for name in self.code_hashes:
            destination=self.folder/'source'/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes((self.root/name).read_bytes())
        if not self.memory.acquire(self.owner,ttl=180):raise RuntimeError('Another executor owns the game lease')
    def check_cancel(self):
        if self.cancel.is_set() or (self.root/'data/v2/STOP').exists():raise InterruptedError('V2 manually stopped')
    def capture(self,label='frame'):
        if not self.memory.acquire(self.owner,ttl=180):raise RuntimeError('Game executor lease lost')
        start=time.perf_counter()
        for attempt in range(3):
            raw=self.adb.call('exec-out','screencap')
            if len(raw)<16:raise RuntimeError('Invalid raw Android screenshot')
            width,height,format,dataspace=struct.unpack('<4I',raw[:16])
            if format not in (1,2) or len(raw)!=16+width*height*4:raise RuntimeError('Unsupported Android raw screenshot format')
            frame=cv2.cvtColor(np.frombuffer(raw,np.uint8,offset=16).reshape(height,width,4),cv2.COLOR_RGBA2BGR)
            # MSI occasionally returns a full solid gray buffer between valid
            # gameplay frames. Reobserve without input; retain the bad buffer.
            if int(np.ptp(frame[::16,::16],axis=(0,1)).max())>=3:break
            path=self.folder/f'{self.frames:04d}-{label}-uniform.jpg';self.frames+=1;cv2.imwrite(str(path),frame)
            self.memory.remember('episodic','v2_capture_gap',self.scope,{'frame':str(path),'retry':attempt+1,'game_input_sent':False},Provenance('android:raw_screencap',method='uniform_buffer_reobservation'),.95,'verified')
            if attempt==2:raise RuntimeError('Three uniform Android capture buffers; current screen unavailable')
            time.sleep(.10)
        latency=(time.perf_counter()-start)*1000
        return self.process_frame(frame,label,latency)
    def process_frame(self,frame,label,latency,metadata=None,detect_puzzles=True):
        """Share perception/persistence for raw checkpoints and V3 live video."""
        if frame.shape[:2]!=(900,1600):raise RuntimeError('V2 calibration requires the observed 1600x900 layout')
        processing=time.perf_counter();self.vision.skip_helmet_templates=self.held_object_kind=='brazier'
        features=self.vision.entities(frame);features.pop('floor_mask',None);spatial_ms=(time.perf_counter()-processing)*1000
        if self.held_object_kind=='brazier' and getattr(self,'held_pose_offset',None):
            held=self.lantern_vision.held_match(frame,getattr(self,'held_actor',None) or features.get('player'))
            if held and self.lantern_vision.carried_actor_visible(frame,held,self.held_pose_offset):
                x,y,w,h=held['bbox'];dx,dy=self.held_pose_offset
                features['player']=[x+w/2+dx*w,y+dy*h];self.held_actor=features['player'];self.vision.last_player=tuple(features['player'])
                features['actor_pose_source']='calibrated_carried_brazier_offset';features['held_object_bbox']=held['bbox']
            else:features['player']=None
        puzzle_started=time.perf_counter()
        features['puzzle_objects']=self.lantern_vision.detect(frame,features.get('player'),holding=self.held_object_kind=='brazier') if detect_puzzles and features['scene']=='jogo' else []
        features['perception_timing']={'spatial_ms':spatial_ms,'puzzle_ms':(time.perf_counter()-puzzle_started)*1000,'puzzle_detection_enabled':detect_puzzles}
        path=self.folder/f'{self.frames:04d}-{label}.jpg';self.frames+=1
        if not cv2.imwrite(str(path),frame,[cv2.IMWRITE_JPEG_QUALITY,90]):raise OSError('Cannot persist V2 screenshot')
        features.update(frame=str(path.relative_to(self.root)),capture_ms=round(latency,2),at=now())
        if metadata:features.update(metadata)
        self.last_frame=frame;self.last_features=features
        if features['scene']=='jogo':self.world_features=features
        if self.frame_callback:self.frame_callback(frame,features)
        return frame,features
    def record(self,action,before,after,metrics):
        row={'at':now(),'action':asdict(action),'before':before,'after':after,'metrics':metrics,'local_position':self.local_position.copy()}
        self.actions.append(row)
        with (self.folder/'events.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        self.memory.remember('episodic','v2_action',self.scope,row,Provenance('v2:fast_control',method='before_after_images'),.9,'verified' if metrics.get('verified') else 'uncertain')
        return row
    def observation(self,features):
        ob=Observation(uid('v2_ob'),features['at'],features['scene'],.85,self.scope,self.scope,'',{**features,'stage_confidence':.85,'stage_observed':False},features['frame'],provenance=Provenance('android:raw_screencap',method='v2_local_visual_features_with_current_run_inherited_stage'))
        self.memory.observe(ob);return ob
    def transition(self,target):
        if target=='jogo':self.check_cancel()
        if self.last_features and now()-self.last_features['at']<.20:
            before_image,before=self.last_frame,self.last_features
        else:before_image,before=self.capture('before-'+target)
        source='pausa' if target=='jogo' else 'jogo'
        if before['scene']==target:return None
        if before['scene']!=source:raise RuntimeError('Cannot transition from unrecognized screen: '+before['scene'])
        if not self.adb.foreground():raise RuntimeError('Guardian Tales left foreground')
        point=(.895,.909) if target=='jogo' else (.106,.13);start=time.perf_counter()
        self.adb.tap(*point,1600,900);deadline=time.monotonic()+4
        while True:
            _,after=self.capture('after-'+target)
            if after['scene']==target:break
            if time.monotonic()>deadline:raise RuntimeError('Interface transition not verified')
            if target=='jogo':self.check_cancel()
            time.sleep(.08)
        return self.record(Action('tap',{'x':point[0],'y':point[1]},'Observed '+target+' transition'),before,after,{'verified':True,'controller_ms':round((time.perf_counter()-start)*1000,2)})
    def pulse(self,action:Action,require_enemy=False,column_context=None):
        self.check_cancel();action.validate();before_image,before=self.capture('before-'+action.op)
        if before['scene']!='jogo':raise RuntimeError('Tactical action requires the gameplay HUD')
        if not self.adb.foreground():raise RuntimeError('Guardian Tales left foreground')
        if action.op=='move' and before.get('health') is not None and before['health']<.25:raise RuntimeError('Low player health in immediate pre-input observation; movement withheld')
        if action.op=='move' and not before.get('player'):raise RuntimeError('Controlled character absent in immediate pre-input observation; movement withheld')
        hazard_endpoint=None
        if action.op=='move' and column_context and getattr(self,'joystick_style','swipe')=='fixed_hold':
            from .hazard_control import crossing_endpoint
            prior=column_context.get('columns',[]) if now()-column_context['at']<2 and math.dist(column_context['player'],before['player'])<25 else []
            hazard_endpoint=crossing_endpoint(before,action.args['direction'],column_context['max_ms'],prior)
            if hazard_endpoint:action=Action('move',{**action.args,'ms':hazard_endpoint['ms']},'Cross an observed spike column and stop in the gap')
        if require_enemy and not before['enemy_count']:
            self.memory.remember('episodic','v2_action_withheld',self.scope,{'action':asdict(action),'reason':'enemy_lost_before_input','frame':before['frame']},Provenance('v2:combat',method='immediate_pre_input_enemy_check'),.95,'verified')
            return {'withheld':True,'reason':'enemy_lost_before_input'}
        operation=None
        if self.goal_id and self.task_id:
            operation=self.memory.prepare(self.goal_id,self.task_id,asdict(action),self.observation(before).id)
            self.memory.operation(operation,'issued')
        start=time.perf_counter()
        if action.op=='move':
            if getattr(self,'joystick_style','swipe')=='fixed_hold':
                from .puzzle_control import DIRECTIONS
                controls=json.loads((self.root/'config.json').read_text())['controls'];x,y=controls['joystick'];vx,vy=DIRECTIONS[action.args['direction']];radius=controls['joystick_radius']*900
                self.adb.hold((x*1600+vx*radius)/1600,(y*900+vy*radius)/900,action.args.get('ms',400),1600,900)
            else:self.adb.move(action.args['direction'],action.args.get('ms',400),1600,900)
        elif action.op in ('attack','skill','interact'):
            config=json.loads((self.root/'config.json').read_text());self.adb.hold(*config['controls'][action.op],action.args.get('ms',400),1600,900)
        elif action.op=='tap':self.adb.tap(action.args['x'],action.args['y'],1600,900)
        else:raise ValueError('Unsupported fast tactical action')
        time.sleep(.08);after_image,after=self.capture('after-'+action.op)
        movement=SpatialVision.motion(before_image,after_image,before['player'],after['player'])
        if action.op=='move' and movement['moved']:
            self.local_position[0]+=movement['effective_dx'];self.local_position[1]+=movement['effective_dy']
        metrics={'verified':bool(movement['moved']) if action.op=='move' else before['enemy_red_area']>after['enemy_red_area'] if action.op=='attack' else False,
                 'controller_ms':round((time.perf_counter()-start)*1000,2),'motion':movement}
        if hazard_endpoint:metrics['hazard_endpoint']=hazard_endpoint
        if operation:metrics['operation_id']=operation
        if operation:self.memory.operation(operation,'observed' if metrics['verified'] else 'uncertain',self.observation(after).id,metrics)
        return self.record(action,before,after,metrics)
    def fight(self,seconds=35):
        deadline=time.monotonic()+seconds;observed=False;clear=0;start=len(self.actions);missing=0;missing_frames=[];perception_recoveries=0
        while time.monotonic()<deadline:
            self.check_cancel();_,features=self.capture('combat-observe')
            if features['scene']!='jogo':raise RuntimeError('Combat screen changed; outcome requires OCR verification')
            if features['health'] is not None and features['health']<.20:raise RuntimeError('Low player health; stop combat and pause')
            enemies=[entity for entity in features['entities'] if entity['kind']=='enemy']
            if not enemies:
                clear+=1
                if clear>=3:
                    if not observed:return {'visible_combat_ended':False,'reason':'transient_detection_not_confirmed','actions':0}
                    result={'visible_combat_ended':True,'first_action':start,'last_action':len(self.actions),'absent_observations':clear,'scope':'visible enemy bars absent, not a stage clear','perception_missing_observations':len(missing_frames),'perception_recoveries':perception_recoveries}
                    self.memory.remember('episodic','v2_combat',self.scope,result,Provenance('v2:combat',method='enemy_bars_and_three_absence_observations'),.85,'verified');return result
                time.sleep(.10);continue
            observed=True;clear=0;player=features['player']
            if not player:
                missing+=1;missing_frames.append(features.get('frame'))
                if missing>=4:raise RuntimeError('Controlled character not confidently located after four bounded observations')
                time.sleep(.10);continue
            if missing:
                perception_recoveries+=1
                self.memory.remember('episodic','v2_perception_recovery',self.scope,{'missing_frames':missing_frames[-missing:],'recovered_frame':features.get('frame'),'inputs_while_missing':0},Provenance('v2:combat',method='bounded_reobservation_without_input'),.9,'verified')
                missing=0
            target=min(enemies,key=lambda e:math.dist((e['bbox'][0]+e['bbox'][2]/2,e['bbox'][1]+e['bbox'][3]/2),player))
            tx,ty=target['bbox'][0]+target['bbox'][2]/2,target['bbox'][1]+target['bbox'][3]/2
            dx,dy=tx-player[0],ty-player[1];distance=math.hypot(dx,dy)
            if distance>140:
                direction=('down' if dy>0 else 'up') if abs(dy)>abs(dx)*1.8 else ('right' if dx>0 else 'left') if abs(dx)>abs(dy)*1.8 else ('down' if dy>0 else 'up')+'_'+('right' if dx>0 else 'left')
                self.pulse(Action('move',{'direction':direction,'ms':min(500,max(120,int((distance-100)*4)))},'Approach an observed enemy'),require_enemy=True)
            else:self.pulse(Action('attack',{'ms':850},'Attack the nearby observed enemy'),require_enemy=True)
        raise RuntimeError('Combat budget exhausted without confirmed visible clearance')
    def frontier_coordinates(self,point,state):
        if self.map_anchor:
            alignment=state.get('anchor_alignment') or self.map_anchor.locate(state)
            if alignment:return {'coordinate_frame':'spawn_reference','anchor_id':self.map_anchor.identity,'point':self.map_anchor.project(point,alignment)}
        return {'coordinate_frame':'local_ui','run_id':self.run_id,'bbox':state['bbox'],'point':list(point)}
    def record_object_vantage(self,state,features,map_frame):
        if not self.map_anchor or not features.get('puzzle_objects') or not features.get('player') or features.get('enemy_count') or features.get('hazard_count'):return
        alignment=state.get('anchor_alignment') or self.map_anchor.locate(state)
        if not alignment:return
        point=self.map_anchor.project(state['player'],alignment)
        content={'run_id':self.run_id,'anchor_id':self.map_anchor.identity,'actor_reference':point,'objects':features['puzzle_objects'],'frame':features['frame'],'map_frame':map_frame,'claim':'objects were visible from this observed actor position; current presence requires fresh observation'}
        dedupe='v2:vantage:'+self.scope+':'+self.map_anchor.identity+':'+str(round(point[0]/16))+':'+str(round(point[1]/16))
        self.memory.remember('episodic','v2_object_vantage',self.scope,content,Provenance(features['frame'],method='observed_objects_with_pre_action_map_pose'),.85,'verified',dedupe=dedupe)
    def frontier_deferred(self,point,state):
        coordinates=self.frontier_coordinates(point,state)
        for record in self.deferred_frontiers:
            if record.get('expires_at',0)<=now() or record['coordinate_frame']!=coordinates['coordinate_frame']:continue
            if coordinates['coordinate_frame']=='spawn_reference':
                if coordinates['anchor_id']!=record.get('anchor_id'):continue
            elif coordinates['run_id']!=record.get('run_id') or coordinates['bbox']!=record.get('bbox'):continue
            if math.dist(coordinates['point'],record['point'])<24:return True
        return False
    def defer_current_frontier(self,reason):
        from .map_navigation import PauseMap
        if not self.last_plan or not self.last_plan_state:return None
        state=self.last_plan_state;point=self.last_plan['target']
        if self.frontier_deferred(point,state):return None
        coordinates=self.frontier_coordinates(point,state)
        dedupe='v2:frontier:'+self.scope+':'+hashlib.sha256(json.dumps(coordinates,sort_keys=True).encode()).hexdigest()
        record={**coordinates,'run_id':self.run_id,'reason':reason,'expires_at':now()+600,'frame':self.last_features['frame'],'dedupe':dedupe,'state':'deferred_after_observed_no_progress'}
        mid=self.memory.remember('working','v2_frontier_blocked',self.scope,record,Provenance('v2:navigation',method='confirmed_stalled_edge_then_bounded_side_steps'),.9,'verified',dedupe=dedupe)
        self.deferred_frontiers.append(record);self.failed_count=0;self.failed_edge=None;self.recovery_count=0
        alternatives={**state,'frontiers':[f for f in state['frontiers'] if not self.frontier_deferred(f['point'],state)]}
        try:next_plan=PauseMap().exploration_plan(alternatives)
        except ValueError:next_plan=None
        return {'memory_id':mid,'blocked':record,'next_target':next_plan['target'] if next_plan else None,'next_direction':next_plan['direction'] if next_plan else None,'claim':'edge stalled; no claim that another branch completes the stage'}
    def reconsider_frontiers(self,reason):
        for record in self.deferred_frontiers:
            if record.get('expires_at',0)<=now():continue
            changed={**record,'expires_at':now(),'state':'retest_allowed_after_'+reason}
            self.memory.remember('working','v2_frontier_blocked',self.scope,changed,Provenance('v2:reconcile',method=reason+'_may_change_gates'),.8,'verified',dedupe=record['dedupe'])
        self.deferred_frontiers=[]
    def navigate_once(self,target=None,allow_combat=True,allow_interaction=True):
        from .map_navigation import PauseMap
        if self.last_features is None or self.last_features['scene']!='pausa':self.transition('pausa')
        image,features=self.capture('planning-map');planning_start=time.perf_counter();parser=PauseMap();map_state=parser.parse(image)
        if self.map_anchor:
            alignment=self.map_anchor.locate(map_state)
            if alignment:self.map_anchor.restore_marker_floor(map_state,alignment)
            if alignment:map_state.update(map_scale=alignment['scale'],anchor_alignment=alignment)
        if target is None:
            if not map_state['frontiers']:raise RuntimeError('No observable map frontier; inspect the actual exit or puzzle')
            available={**map_state,'frontiers':[f for f in map_state['frontiers'] if not self.frontier_deferred(f['point'],map_state)]}
            plan=parser.exploration_plan(available);target=plan['target']
        else:plan=parser.next_motion(map_state,target)
        if not plan:raise RuntimeError('Already at the observed destination; need a new objective')
        self.last_plan=plan;self.last_plan_state=map_state
        position=self.frontier_coordinates(map_state['player'],map_state)['point']
        edge=(round(position[0]/24),round(position[1]/24),plan['direction'])
        if self.failed_count>=2 and self.failed_edge==edge:
            recovery=parser.recovery(map_state,plan['direction'])
            if not recovery or self.recovery_count>=3:raise RuntimeError('Observed edge blocked; bounded side-step recovery unavailable')
            plan={**plan,**recovery};self.recovery_count+=1
        map_data={key:value for key,value in map_state.items() if key!='floor'}
        self.memory.remember('working','v2_spatial',self.scope,{'map':map_data,'plan':plan,'run_id':self.run_id},Provenance('v2:pause_map',method='observed_floor_bfs'),.8,'hypothesis',dedupe='v2-spatial:'+self.scope)
        with (self.folder/'plans.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps({'at':now(),'map':map_data,'plan':plan})+'\n')
        planning_ms=round((time.perf_counter()-planning_start)*1000,3)
        self.transition('jogo');game=self.last_features
        self.record_object_vantage(map_state,game,features['frame'])
        if game['health'] is not None and game['health']<.25:raise RuntimeError('Low player health; navigation interrupted for recovery')
        if game['enemy_count']:
            if not allow_combat:raise RuntimeError('Combat interrupts puzzle navigation')
            combat=self.fight()
            if combat.get('visible_combat_ended'):self.reconsider_frontiers('new_visible_combat')
            self.transition('pausa');return {'kind':'combat','plan':plan,'result':combat,'planning_ms':planning_ms}
        if self.interaction_handler and allow_interaction:
            interaction=self.interaction_handler(self)
            if interaction.get('attempted'):
                if not interaction['verified']:raise RuntimeError('Observed interaction had no confirmed effect; not retrying blindly')
                self.transition('pausa');return {'kind':'interaction','result':interaction,'plan':plan,'planning_ms':planning_ms}
        # Recheck moving threats on the live image, rather than treating the
        # static pause-map floor as an obstacle-free corridor.
        player=game.get('player');vectors={'up':(0,-1),'down':(0,1),'left':(-1,0),'right':(1,0)}
        vx,vy=vectors[plan['direction']]
        if player and plan['direction'] not in ('left','right'):
            for entity in game['entities']:
                if entity['kind']!='hazard':continue
                x,y,bw,bh=entity['bbox'];dx=x+bw/2-player[0];dy=y+bh-20-player[1]
                ahead=dx*vx+dy*vy;cross=abs(dx*vy-dy*vx)
                if 0<ahead<300 and cross<140:
                    plan['ms']=min(plan['ms'],350);plan['hazard_observed']=entity
                    if ahead<180 and cross<80:
                        avoid=parser.recovery(map_state,plan['direction'])
                        if avoid:plan={**plan,**avoid,'strategy':'observed_hazard_side_step'}
                    break
        if self.joystick_style=='fixed_hold' and plan.get('reference_distance'):
            # Preserve the observed first straight segment after changing the
            # input speed; do not carry a long pulse through a map corner.
            plan['ms']=min(plan['ms'],max(80,int(plan['reference_distance']/.0592*.90)))
        action=Action('move',{'direction':plan['direction'],'ms':plan['ms']},'Move toward an observed map frontier')
        context=None
        if player and plan['direction'] in ('left','right'):
            context={'player':player,'at':game['at'],'columns':[e['bbox'][0]+e['bbox'][2]/2 for e in game['entities'] if e['kind']=='hazard'],'max_ms':min(1500,max(80,int(plan.get('reference_distance',0)/.0592*.90)))}
        row=self.pulse(action,column_context=context)
        if row['metrics'].get('hazard_endpoint'):plan.update(ms=row['action']['args']['ms'],hazard_endpoint=row['metrics']['hazard_endpoint'])
        self.transition('pausa')
        after_image,after_features=self.capture('navigation-result-map');after_map=parser.parse(after_image)
        dx=after_map['player'][0]-map_state['player'][0];dy=after_map['player'][1]-map_state['player'][1]
        vectors={'up':(0,-1),'down':(0,1),'left':(-1,0),'right':(1,0)};vx,vy=vectors[plan['direction']]
        same_map=all(abs(a-b)<8 for a,b in zip(map_state['bbox'],after_map['bbox']))
        progress=dx*vx+dy*vy
        result={'before':map_state['player'],'after':after_map['player'],'dx':dx,'dy':dy,'direction_progress':progress,'same_map_extent':same_map,'verified':same_map and progress>2}
        row['metrics']['map_motion']=result
        row['metrics']['verified']=result['verified'] if same_map else row['metrics']['verified']
        if self.map_anchor:
            aligned=self.map_anchor.motion(map_state,after_map,plan['direction'])
            row['metrics']['aligned_map_motion']=aligned
            if aligned.get('before_alignment') and aligned.get('after_alignment'):row['metrics']['verified']=aligned['verified']
        verified=row['metrics']['verified']
        self.failed_count=self.failed_count+1 if not verified and self.failed_edge==edge else 1 if not verified else 0
        self.failed_edge=edge if not verified else None
        if row['metrics'].get('operation_id'):
            self.memory.operation(row['metrics']['operation_id'],'observed' if row['metrics']['verified'] else 'uncertain',self.observation(after_features).id,row['metrics'])
        evidence={'run_id':self.run_id,'plan':plan,'result':result,'aligned_map_motion':row['metrics'].get('aligned_map_motion'),'verified':verified}
        self.memory.remember('episodic','v2_path_attempt',self.scope,evidence,Provenance('v2:pause_map',method='pin_wall_clearance_and_validated_map_alignment'),.9,'verified' if verified else 'uncertain')
        with (self.folder/'navigation.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps({'at':now(),**evidence})+'\n')
        return {'kind':'navigation','plan':plan,'metrics':row['metrics'],'planning_ms':planning_ms}
    def close(self):
        self.memory.release(self.owner)
        report={'run_id':self.run_id,'scope':self.scope,'kind':self.kind,'actions':self.actions,'seconds':round(time.perf_counter()-self.start,3),'code_hashes_at_start':self.code_hashes}
        (self.folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');return report
