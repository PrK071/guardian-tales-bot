"""Continuous controls sharing V1/V2 capture, hierarchy, journal and executor lease."""
import hashlib,json,math,time
import cv2
from ..contracts import Provenance
from ..spatial import SpatialVision
from ..fast_control import FastSession
from ..map_anchor import SpawnMapAnchor
from ..map_navigation import PauseMap
from ..stage_v2 import InteractionVision
from .input_backend import ScrcpyTouch
from .continuous import ContinuousActions
from .observation import LiveObserver,ThreatGate
from .segments import SegmentPlanner
from .combat import CombatController
from .hazards import solid_spike

class GameplaySession(FastSession):
    def __init__(self,root,adb,memory,cancel=None,scope='world:1:passage:1',run_id=None,video=False):
        super().__init__(root,adb,memory,cancel,scope,run_id,artifact_base='data/v3')
        self.kind='v3_continuous_stage_execution';self.backend=ScrcpyTouch(self.root,adb,self.folder,video=video);self.controls=None;self.active_operation=None;self.segment_results=[];self.combat_results=[];self.video_sequence=0;self.last_confirmed_enemy=None
        try:
            anchors=memory.retrieve(scope,kind='v2_spawn_anchor',include_global=False,limit=1)
            if not anchors or anchors[0]['validation']!='verified':raise RuntimeError('A validated map reference is required for this stage')
            self.map_anchor=SpawnMapAnchor.load(anchors[0]['content'],self.root);self.map_anchor.save(self.folder/'spawn-map-anchor.png')
            controls=json.loads((self.root/'config.json').read_text())['controls'];profiles=json.loads((self.root/'evaluations/v3/input-profile.json').read_text());self.speeds={}
            for mode in ('move','run'):
                compatible=[]
                for sample in profiles:
                    source=self.root/'data/v3'/sample['run_id']/'source/config.json'
                    if sample['mode']==mode and sample['anchor_id']==self.map_anchor.identity and source.exists() and json.loads(source.read_text())['controls']==controls:compatible.append(sample['reference_pixels_per_ms'])
                if compatible:self.speeds[mode]=sorted(compatible)[len(compatible)//2]
            if 'move' not in self.speeds:raise RuntimeError('Compatible measured walking calibration unavailable')
            self.neutral=cv2.imread(str(self.root/'data/v2/v2_calibration_45124c972be4410b/0048-after-jogo.jpg'));self.interaction=InteractionVision(self.root)
            self.backend.connect();self.controls=ContinuousActions(self.backend,controls,self.cancel,[self.root/'data/v2/STOP',self.root/'data/v3/STOP'],self.can_run,self.log_control)
        except Exception:
            self.backend.close();super().close();raise
    def check_cancel(self):
        if (self.root/'data/v3/STOP').exists():raise InterruptedError('V3 manually stopped')
        super().check_cancel()
    def capture_live(self,label):
        if not self.backend.video:return self.capture(label)
        if not self.memory.acquire(self.owner,ttl=180):raise RuntimeError('Game executor lease lost')
        started=time.perf_counter();frame,sample=self.backend.video.frame_after(self.video_sequence);self.video_sequence=sample['sequence']
        return self.process_frame(frame,label,(time.perf_counter()-started)*1000,{'capture_source':'scrcpy_h264','video_sample':sample},detect_puzzles=False)
    def can_run(self):
        if self.held_object_kind or self.neutral is None or not self.last_features or self.last_features['scene']!='jogo':return False
        return float(cv2.matchTemplate(InteractionVision.mask(self.last_frame),InteractionVision.mask(self.neutral),cv2.TM_CCOEFF_NORMED)[0,0])>.92
    def log_control(self,row):
        row['operation_id']=self.active_operation
        with (self.folder/'controls.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        self.memory.remember('episodic','v3_continuous_action',self.scope,{'run_id':self.run_id,**row},Provenance('v3:persistent_touch',method='explicit_down_up_and_independent_stop_timer'),.9,'uncertain')
    def prepare_continuous(self,op,args):
        if not self.goal_id or not self.task_id:return None
        before=self.observation(self.last_features)
        token=self.memory.prepare(self.goal_id,self.task_id,{'op':op,'args':args,'schema':'v3'},before.id);self.memory.operation(token,'issued');self.active_operation=token;return token
    def verify_continuous(self,result,verified):
        if self.active_operation:
            self.memory.operation(self.active_operation,'observed' if verified else 'uncertain',self.observation(self.last_features).id,result);self.active_operation=None
    def map_state(self,label='v3-map-checkpoint'):
        self.transition('pausa');frame,features=self.capture(label);state=PauseMap().parse(frame);alignment=self.map_anchor.locate(state)
        if not alignment:raise RuntimeError('Stage map no longer matches the validated reference')
        self.map_anchor.restore_marker_floor(state,alignment)
        state.update(map_scale=alignment['scale'],anchor_alignment=alignment)
        return state,alignment,self.map_anchor.project(state['player'],alignment),features
    @staticmethod
    def raw_target(reference,alignment):return [(reference[i]-alignment['source_origin'][i])*alignment['scale']+alignment['top_left'][i] for i in range(2)]
    def preflight_enemy(self,features):
        """Reobserve a distant transient before choosing a combat interrupt."""
        if not features.get('combat_present',features['enemy_count']):return False
        gate=ThreatGate()
        if gate.update({'sequence':0,'features':features}):self.last_confirmed_enemy=dict(features);return True
        self.check_cancel();_,fresh=self.capture('v3-distant-threat-preflight')
        if fresh['scene']!='jogo' or not fresh.get('player'):raise RuntimeError('Threat preflight lost the gameplay scene or actor')
        if fresh.get('health') is not None and fresh['health']<.25:raise RuntimeError('Threat preflight health too low')
        confirmed=gate.update({'sequence':1,'features':fresh})
        if confirmed:self.last_confirmed_enemy=dict(fresh)
        return confirmed
    def navigate_to(self,target,tolerance=8,run=False,allow_npc_bypass=False,max_segment_ms=None,_checkpoint=None):
        self.check_cancel();begun=time.perf_counter()
        cached=bool(_checkpoint and time.time()-_checkpoint[3]['at']<4 and _checkpoint[4]==len(self.controls.actions) and not self.backend.held and self.last_features['scene']=='jogo')
        if cached:state,alignment,before,before_features,_=_checkpoint
        else:state,alignment,before,before_features=self.map_state('v3-segment-before-map')
        if math.dist(before,target)<=tolerance:return {'verified':True,'already_at_checkpoint':True,'target':target,'before':before,'after':before,'seconds':time.perf_counter()-begun,'model_calls':0}
        run=bool(run and 'run' in self.speeds);planning=time.perf_counter();plan=SegmentPlanner(self.speeds['run' if run else 'move']).plan(state,self.raw_target(target,alignment));planning_ms=(time.perf_counter()-planning)*1000
        if not plan['segments']:raise RuntimeError('No nonzero route segment to the observed checkpoint')
        if not cached:self.transition('jogo')
        if time.time()-self.last_features['at']<.25:features=self.last_features
        else:_,features=self.capture('v3-segment-preflight')
        if features['scene']!='jogo':raise RuntimeError('Segment preflight lost the gameplay scene')
        if features['health'] is not None and features['health']<.25:raise RuntimeError('Segment preflight health too low')
        if self.preflight_enemy(features):
            self.transition('pausa');return {'verified':False,'reason':'enemy_detected','target':target,'model_calls':0}
        # Hit flashes briefly recolor the real helmet. Observe again with all
        # controls released; never extrapolate a pose or move without it.
        for _ in range(2):
            if features.get('player'):break
            _,features=self.capture('v3-segment-actor-reobservation')
            if features['scene']!='jogo':raise RuntimeError('Segment preflight gameplay scene changed')
            if features['health'] is not None and features['health']<.25:raise RuntimeError('Segment preflight health too low')
            if self.preflight_enemy(features):
                self.transition('pausa');return {'verified':False,'reason':'enemy_detected','target':target,'model_calls':0}
        if not features['player']:raise RuntimeError('Segment preflight lost the controlled character')
        if run and not self.can_run():run=False;plan=SegmentPlanner(self.speeds['move']).plan(state,self.raw_target(target,alignment))
        sequence=[{'op':'move_hold','direction':s['direction'],'duration_ms':s['duration_ms'],'run':run} for s in plan['segments']]
        partial=False
        if max_segment_ms is not None:
            # Unknown floor: finish one measured observation horizon. A known
            # corridor has no such cap and may use the full calibrated hold.
            sequence=sequence[:1];partial=sequence[0]['duration_ms']>max_segment_ms or len(plan['segments'])>1
            sequence[0]['duration_ms']=min(sequence[0]['duration_ms'],max_segment_ms)
        self.prepare_continuous('execute_sequence',{'sequence':sequence,'target_reference':target,'before_reference':before,'tolerance':tolerance})
        observer=LiveObserver(self).start();seen_sequence=-1;missing=0;threat_gate=ThreatGate()
        def policy(snapshot):
            nonlocal seen_sequence,missing
            current=snapshot['features']
            if current['scene']!='jogo':return 'screen_changed'
            if current['health'] is not None and current['health']<.25:return 'low_health'
            if threat_gate.update(snapshot):self.last_confirmed_enemy=dict(current);return 'enemy_detected'
            if current.get('hazard_count') and current.get('player'):
                for entity in current.get('entities',[]):
                    if entity['kind']!='hazard' or not solid_spike(snapshot['frame'],entity):continue
                    x,y,w,h=entity['bbox']
                    if math.dist(current['player'],[x+w/2,y+h-20])<150:return 'observed_hazard'
            if snapshot['sequence']!=seen_sequence:
                seen_sequence=snapshot['sequence'];missing=0 if current.get('player') else missing+1
                if missing>=2:return 'actor_lost'
            if run and self.interaction.affordance(snapshot['frame']):return 'run_affordance_changed'
            if not allow_npc_bypass and self.interaction.affordance(snapshot['frame']):return 'npc_checkpoint'
        controls=[]
        try:controls=self.controls.execute_sequence(sequence,monitor=lambda:observer.reason(policy))
        finally:
            self.backend.release_all();observation_report=observer.close()
        _,_,after,after_features=self.map_state('v3-segment-after-map');error=math.dist(after,target);verified=error<=tolerance
        reason=controls[-1]['outcome'] if controls else 'no_control_action'
        result={'verified':verified,'reused_map_checkpoint':cached,'partial_observation_horizon':partial,'progress_verified':math.dist(before,after)>3,'reason':reason,'target':target,'before':before,'after':after,'goal_error_reference_pixels':error,'net_progress_reference_pixels':math.dist(before,after),'planning_ms':planning_ms,'seconds':time.perf_counter()-begun,'plan':plan,'controls':controls,'observations':observation_report,'before_frame':before_features['frame'],'after_frame':after_features['frame'],'model_calls':0}
        self.verify_continuous(result,verified);self.segment_results.append(result)
        self.memory.remember('episodic','v3_route_segment',self.scope,{'run_id':self.run_id,**result},Provenance(after_features['frame'],method='calibrated_continuous_segment_then_aligned_map_checkpoint'),.95,'verified' if verified else 'uncertain')
        return result
    def navigate_once(self,target=None,allow_combat=True,allow_interaction=True,preferred_direction=None):
        state,alignment,before_point,map_features=self.map_state('v3-frontier-map');parser=PauseMap();checkpoint=(state,alignment,before_point,map_features,len(self.controls.actions))
        if target is None:
            available={**state,'frontiers':[f for f in state['frontiers'] if not self.frontier_deferred(f['point'],state)]}
            if preferred_direction:
                vx,vy=ContinuousActions.vector(preferred_direction);px,py=state['player']
                forward=[f for f in available['frontiers'] if (f['point'][0]-px)*vx+(f['point'][1]-py)*vy>10*state.get('map_scale',1)]
                if forward:available={**available,'frontiers':forward}
            plan=parser.exploration_plan(available)
            # The snapped path endpoint is inside observed floor. A frontier's
            # outer boundary itself is not a safe place to stand.
            target=plan['path'][-1]
        else:plan=parser.next_motion(state,target)
        if not plan:raise RuntimeError('No nonzero observed route segment')
        self.last_plan=plan;self.last_plan_state=state
        reference=self.map_anchor.project(target,alignment)
        self.transition('jogo');features=self.last_features;self.record_object_vantage(state,features,map_features['frame'])
        if self.preflight_enemy(features):
            if not allow_combat:raise RuntimeError('Combat interrupts puzzle navigation')
            return {'kind':'combat','result':self.fight_continuously(),'plan':plan,'planning_ms':0}
        if allow_interaction and self.interaction_handler:
            interaction=self.interaction_handler(self)
            if interaction.get('attempted'):
                self.transition('pausa');return {'kind':'interaction','result':interaction,'plan':plan,'planning_ms':0}
        if math.dist(self.map_anchor.project(state['player'],alignment),reference)<=10:
            from .exploration import visible_floor_horizon
            extension=visible_floor_horizon(self.last_frame,features,plan['direction'])
            if not extension:raise RuntimeError('Observed map frontier reached but no clear live floor extends it')
            before_frame=self.last_frame.copy();before_features=features;self.prepare_continuous('frontier_extension',extension);observer=LiveObserver(self).start()
            def extension_guard(snap):
                f=snap['features']
                if f['scene']!='jogo' or not f.get('player'):return 'actor_or_screen_changed'
                if f.get('combat_present',f['enemy_count']):return 'enemy_detected'
                if f['health'] is not None and f['health']<.25:return 'low_health'
                if f['hazard_count']:return 'observed_hazard'
            try:control=self.controls.move_hold(extension['direction'],extension['duration_ms'],monitor=lambda:observer.reason(extension_guard))
            finally:self.backend.release_all();observation_report=observer.close()
            after_frame,after=self.capture('v3-frontier-live-end');motion=SpatialVision.motion(before_frame,after_frame,before_features['player'],after['player'])
            _,_,after_point,_=self.map_state('v3-frontier-extension-map');before_point=self.map_anchor.project(state['player'],alignment)
            result={'verified':math.dist(before_point,after_point)>3,'before':before_point,'after':after_point,'live_floor_horizon':extension,'control':control,'observations':observation_report,'motion':motion}
            self.verify_continuous(result,result['verified']);return {'kind':'navigation','plan':plan,'metrics':result,'planning_ms':0}
        row=self.navigate_to(reference,tolerance=10,allow_npc_bypass=True,max_segment_ms=1200,_checkpoint=checkpoint)
        if row.get('reason')=='enemy_detected':
            if not allow_combat:raise RuntimeError('Combat interrupts puzzle navigation')
            return {'kind':'combat','result':self.fight_continuously(),'plan':plan,'planning_ms':row.get('planning_ms',0)}
        verified=row.get('verified') or row.get('progress_verified',False)
        edge=(round(row.get('before',[0,0])[0]/24),round(row.get('before',[0,0])[1]/24),plan['direction'])
        self.failed_count=self.failed_count+1 if not verified and self.failed_edge==edge else 0 if verified else 1;self.failed_edge=None if verified else edge
        return {'kind':'navigation','plan':plan,'metrics':{'verified':verified,'aligned_map_motion':row,'reason':row.get('reason')},'planning_ms':row.get('planning_ms',0)}
    def pulse(self,action,require_enemy=False,column_context=None):
        """Keep V2 puzzle/interaction contracts, using the continuous backend."""
        action.validate();self.check_cancel()
        reused=bool(self.last_features and self.last_features.get('scene')=='jogo' and self.last_features.get('player') and time.time()-self.last_features.get('at',0)<.35)
        if reused:before_image,before=self.last_frame,self.last_features
        else:before_image,before=self.capture('v3-before-'+action.op)
        if before['scene']!='jogo' or not self.adb.foreground():raise RuntimeError('Continuous pulse requires foreground gameplay')
        if require_enemy and not before['enemy_count']:return {'withheld':True,'reason':'enemy_lost_before_input'}
        if action.op=='move' and (not before.get('player') or before.get('health',1) is not None and before['health']<.25):raise RuntimeError('Pulse movement preflight unavailable')
        self.prepare_continuous(action.op,action.args);begun=time.perf_counter();ms=action.args.get('ms',400)
        if action.op=='move':control=self.controls.move_hold(action.args['direction'],ms)
        elif action.op=='attack':control=self.controls.attack_hold(ms)
        elif action.op=='skill':control=self.controls.use_skill()
        elif action.op=='interact':
            x,y=self.controls.point('interact');self.backend.down(4,x,y)
            try:self.cancel.wait(ms/1000);self.check_cancel()
            finally:self.backend.up(4)
            control={'kind':'interact','requested_ms':ms}
        else:raise ValueError('Unsupported V3 local pulse')
        after_image,after=self.capture('v3-after-'+action.op);motion=SpatialVision.motion(before_image,after_image,before['player'],after['player'])
        metrics={'reused_preinput_observation':reused,'verified':bool(motion['moved']) if action.op=='move' else False,'motion':motion,'controller_ms':(time.perf_counter()-begun)*1000,'continuous_control':control,'operation_id':self.active_operation}
        self.verify_continuous(metrics,metrics['verified']);return self.record(action,before,after,metrics)
    def fight_continuously(self,seconds=60,skill_ready=None,prior_enemy_evidence=None):
        self.transition('jogo')
        if prior_enemy_evidence is None:prior_enemy_evidence=getattr(self,'last_confirmed_enemy',None)
        from .carry_combat import arrow_visible,fight_with_carried_item
        if self.held_object_kind=='brazier' and arrow_visible(self,self.last_frame):
            result=fight_with_carried_item(self,seconds,getattr(self,'recover_item_after_combat',True),prior_enemy_evidence=prior_enemy_evidence)
            if result.get('visible_combat_ended'):self.last_confirmed_enemy=None
            return result
        if time.time()-self.last_features['at']>.3:self.capture('v3-before-combat-journal')
        self.prepare_continuous('continuous_combat',{'seconds':seconds})
        result=CombatController(self,self.controls,skill_ready,prior_enemy_evidence).run(seconds);self.transition('pausa');self.capture('v3-combat-checkpoint')
        self.verify_continuous(result,result['visible_combat_ended']);self.combat_results.append(result)
        if result.get('visible_combat_ended'):self.last_confirmed_enemy=None
        return result
    def close(self):
        errors=[]
        if self.controls:
            try:self.controls.close()
            except Exception as exc:errors.append(str(exc))
        backend=self.backend.close()
        if self.active_operation:
            try:self.verify_continuous({'reason':'session_closed_before_verification'},False)
            except Exception as exc:errors.append(str(exc))
        report=super().close();report.update(continuous_actions=self.controls.actions if self.controls else [],segments=self.segment_results,combats=self.combat_results,backend=backend,close_errors=errors)
        (self.folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');return report
