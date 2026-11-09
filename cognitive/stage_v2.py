"""V2 phase executor on the existing worker, SQLite tasks and Android controls."""
from pathlib import Path
import json,math,time
import cv2
import numpy as np
from .contracts import Action,Provenance,State,Task,uid,now
from .fast_control import FastSession
from .map_navigation import PauseMap
from .perception import normalize

def completion_evidence(snap):
    text=normalize(' '.join(word['text'] for word in snap.get('words',[])))
    phrase=any(token in text for token in ('stage clear','etapa concluida','etapa completada','fase concluida','conclusao da etapa')) or 'etapacompletada' in text.replace(' ','')
    return bool(phrase and snap.get('scene')=='resultado' and not snap.get('blocked') and 'continuar' not in text)

def compile_solution(memories,scope,observed):
    """Extract one bounded game hypothesis; prose is never executable code."""
    for memory in memories:
        if memory.get('scope')!=scope or memory.get('validation') in ('contradicted','uncertain'):continue
        text=normalize(json.dumps(memory.get('content',{}),ensure_ascii=False))
        if 'bomb' in text and ('rock' in text or 'rocha' in text) and observed.get('rock') and observed.get('bomb'):
            return {'validation':'hypothesis','memory_id':memory['id'],'steps':['approach_observed_bomb','interact_and_verify_pickup','face_observed_rock','interact_and_verify_obstacle_change']}
    return None

def compile_route_hypothesis(memories,scope):
    for memory in memories:
        if memory.get('scope')!=scope or memory.get('validation') in ('contradicted','uncertain'):continue
        text=normalize(json.dumps(memory.get('content',{}),ensure_ascii=False))
        if all(token in text for token in ('branch','rock','combat')):
            return {'validation':'hypothesis','memory_id':memory['id'],'strategy':'try_another_observed_frontier_after_stall','claim':'Reported alternate branches are a reason to explore; neither a bypass nor stage completion is proven.'}
    return None

class InteractionVision:
    def __init__(self,root):
        reference=cv2.imread(str(Path(root)/'captures/1794088601124454200-before.png'))
        self.template=self.mask(reference) if reference is not None else None
    @staticmethod
    def mask(frame):return cv2.inRange(frame[685:790,1380:1485],(205,205,205),(255,255,255))
    def affordance(self,frame):
        if self.template is None:return False
        return float(cv2.matchTemplate(self.mask(frame),self.template,cv2.TM_CCOEFF_NORMED)[0,0])>.90
    @staticmethod
    def dialogue(frame):
        hsv=cv2.cvtColor(frame[140:650,450:1150],cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,(10,0,170),(45,110,255))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        return any(cv2.boundingRect(c)[2]>150 and cv2.boundingRect(c)[3]>50 and cv2.contourArea(c)>5000 for c in contours)

class StageRunner:
    def __init__(self,bot,runtime,root):
        self.bot=bot;self.runtime=runtime;self.root=Path(root);self.memory=runtime.memory
        self.metrics={'cycles':0,'replans':0,'recoveries':0,'frontier_deferrals':0,'no_progress':0,'perception_failures':0,'perception_gaps':0,'navigation_failures':0,'verification_failures':0,'model_calls':0,'input_tokens':0,'output_tokens':0,'decision_ms':[],'cycle_ms':[],'timing_scope':'isolated_local_planning_ms','puzzle_attempts':0,'puzzle_verified':0,'completed':False}
    def configure_map_reference(self,session,state,scope):
        from .map_anchor import SpawnMapAnchor
        anchors=self.memory.retrieve(scope,kind='v2_spawn_anchor',include_global=False,limit=1)
        reference=SpawnMapAnchor.load(anchors[0]['content'],self.root) if anchors and anchors[0]['validation']=='verified' else None
        tickets=self.memory.retrieve(scope,kind='v2_prepared_spawn',include_global=False,limit=1)
        ticket=tickets[0] if tickets and tickets[0]['validation']=='verified' else None
        source=ticket['content'] if ticket else None
        if (reference is None or reference.spawn_point is None) and source:
            path=Path(source['frame']).resolve()
            if not path.is_relative_to(self.root.resolve()):raise RuntimeError('Prepared spawn evidence outside project')
            reference=SpawnMapAnchor.from_map(PauseMap().parse(cv2.imread(str(path))))
        session.map_anchor=reference
        if reference:
            session.anchor_metadata=reference.save(session.folder/'spawn-map-anchor.png')
            session.anchor_metadata['source_memory_id']=anchors[0]['id'] if anchors else ticket['id']
            if not anchors or anchors[0]['content'].get('spawn_point') is None:
                self.memory.remember('semantic','v2_spawn_anchor',scope,session.anchor_metadata,Provenance(source['frame'],method='verified_preparation_spawn_reference'),.95,'verified',dedupe='v2:spawn-anchor:'+scope)
        fresh=bool(source and not source.get('consumed_by_run') and now()-source['prepared_at']<180)
        initial=bool(reference and reference.is_spawn(state) and fresh)
        if initial:
            self.memory.remember('working','v2_prepared_spawn',scope,{**source,'consumed_by_run':session.run_id},Provenance(source['frame'],method='fresh_entry_consumed_by_verified_initial_trial'),.98,'verified',dedupe='v2:prepared-spawn:'+scope)
            session.reconsider_frontiers('verified_new_stage_entry')
        return initial
    def snapshot(self,session,task,kind,data):
        ob=session.observation(session.last_features)
        self.runtime.evidence(ob)
        task.data.update(run_id=session.run_id,last_event=kind,last_result=data);self.memory.save_task(task)
        self.memory.checkpoint(self.runtime.goal_id,ob,{'v2':True,'run_id':session.run_id,'event':kind,'result':data,'metrics':self.metrics})
        self.runtime.event('v2_'+kind,task_id=task.id,data=data)
        self.runtime.last_decision='v2_'+kind
        self.runtime.metrics.update(cycles=self.metrics['cycles'],actions=len(getattr(session,'actions',[])),replans=self.metrics['replans'],failures=self.metrics['perception_failures']+self.metrics['navigation_failures']+self.metrics['verification_failures'],model_calls=0,input_tokens=0,output_tokens=0,decision_ms=self.metrics['decision_ms'])
        self.bot.note='V2 · '+{'cycle':'explorando','start':'iniciando','blocker_research':'consultando memória e replanejando','puzzle_resolved':'obstáculo resolvido'}.get(kind,kind)
    def verify_completion(self):
        evidence=[]
        for _ in range(2):
            ob=self.runtime.environment.observe();self.runtime.evidence(ob)
            if not completion_evidence(self.bot.snapshot):return []
            evidence.append(ob.id)
        return evidence
    def research_blocker(self,session,reason):
        # Research runs only after gameplay is frozen. No external text is sent
        # to the action executor; a solution remains a hypothesis until tested.
        if session.last_features['scene']=='jogo':session.transition('pausa')
        memories=self.memory.retrieve(session.scope,kind='research',include_global=False,limit=3)
        if not memories and self.runtime.research:
            self.runtime.research.reset_budget()
            self.runtime.research.investigate(session.scope,reason,self.runtime.goal_id)
            memories=self.memory.retrieve(session.scope,kind='research',include_global=False,limit=3)
        kinds={e['kind'] for e in (session.world_features or {}).get('entities',[])}
        solution=compile_solution(memories,session.scope,{'rock':'rock_obstacle_candidate' in kinds,'bomb':'bomb_candidate' in kinds})
        if solution:
            solution['execution_status']='requires_pickup_and_obstacle_change_verification'
            self.memory.remember('working','v2_puzzle_hypothesis',session.scope,solution,Provenance('v2:research_to_steps'),.6,'hypothesis')
        return {'memory_ids':[m['id'] for m in memories],'solution':solution,'route_hypothesis':compile_route_hypothesis(memories,session.scope)}
    def interact(self,session):
        vision=InteractionVision(self.root)
        if getattr(session,'last_features',None) and now()-session.last_features.get('at',0)<.50:frame=session.last_frame
        else:frame,_=session.capture('interaction-check')
        if not vision.affordance(frame):return {'verified':False,'reason':'no_observed_interaction_affordance'}
        before=vision.dialogue(frame);session.pulse(Action('interact',{'ms':100},'Activate the observed conversation button'))
        after=vision.dialogue(session.last_frame);verified=not before and after
        result={'attempted':True,'verified':verified,'before_dialogue':before,'after_dialogue':after}
        self.memory.remember('episodic','v2_interaction',session.scope,result,Provenance('v2:interaction',method='chat_template_then_dialogue_region_change'),.85,'verified' if verified else 'uncertain')
        if verified:
            for _ in range(6):
                if not vision.dialogue(session.last_frame):break
                session.pulse(Action('interact',{'ms':100},'Advance an observed dialogue'))
            if vision.dialogue(session.last_frame):raise RuntimeError('Dialogue exceeded the bounded interaction budget')
        return result
    def run(self,max_steps=100,max_seconds=900):
        max_steps=min(100,max(1,int(max_steps)));max_seconds=min(1800,max(10,int(max_seconds)))
        self.runtime.open_goal('V2: complete Kanterbury Forest Passage 1 with real evidence')
        try:
            initial=self.runtime.environment.observe();self.runtime.evidence(initial);self.runtime.reconcile(initial)
            if initial.scope!='world:1:passage:1' or initial.scene!='pausa':raise RuntimeError('V2 requires the observed Passage 1 pause map; no blind stage selection')
        except Exception as error:
            self.memory.goal_state(self.runtime.goal_id,State.BLOCKED)
            for previous in self.memory.tasks(self.runtime.goal_id):
                if previous.state!=State.COMPLETED:previous.state=State.BLOCKED;self.memory.save_task(previous)
            self.runtime.event('v2_initial_observation_failed',error=str(error),game_input_sent=False)
            raise
        root=[task for task in self.memory.tasks(self.runtime.goal_id) if task.kind=='complete_stage'][-1]
        root.scope=initial.scope;root.state=State.RUNNING;self.memory.save_task(root)
        task=Task(uid('v2_task'),self.runtime.goal_id,'v2_explore','Navigate observed frontiers, resolve encounters, verify stage result',initial.scope,parent_id=root.id,success={'stage_result_observations':2},max_attempts=100,state=State.RUNNING)
        self.memory.save_task(task);self.memory.goal_state(self.runtime.goal_id,State.RUNNING)
        session=FastSession(self.root,self.bot.adb,self.memory,self.bot.cancel,initial.scope,uid('v2_trial'))
        session.goal_id=self.runtime.goal_id;session.task_id=task.id
        session.kind='stage_initialization_not_completed'
        session.interaction_handler=self.interact
        session.frame_callback=getattr(self.bot,'publish_fast_frame',None)
        deadline=time.monotonic()+max_seconds;outcome='budget_exhausted';reason='';failures=0;deferred_pending=None
        try:
            session.capture('initial');initial_map=PauseMap().parse(session.last_frame)
            start_verified=self.configure_map_reference(session,initial_map,initial.scope)
        except Exception:
            session.close();raise
        memories=self.runtime.context(initial)
        self.snapshot(session,task,'start',{'initial_spawn_verified':start_verified,'retrieved_memory_ids':[m['id'] for m in memories],'objective':'Defeat monsters and confirm actual result screen'})
        self.runtime.running=True
        try:
            for step in range(max_steps):
                session.check_cancel();task.attempts+=1;self.metrics['cycles']+=1
                if time.monotonic()>deadline:break
                begun=time.perf_counter()
                try:
                    result=session.navigate_once()
                    self.metrics['cycle_ms'].append(round((time.perf_counter()-begun)*1000,3))
                    if isinstance(result.get('planning_ms'),(int,float)):self.metrics['decision_ms'].append(result['planning_ms'])
                    if result['kind']=='combat':
                        self.metrics['perception_gaps']+=result.get('result',{}).get('perception_missing_observations',0)
                        self.metrics['recoveries']+=result.get('result',{}).get('perception_recoveries',0)
                    moved=result.get('metrics',{}).get('verified',False)
                    if moved and deferred_pending:
                        self.metrics['recoveries']+=1
                        self.memory.remember('episodic','v2_route_strategy_tested',session.scope,{'replan':deferred_pending,'progress_frame':session.last_features['frame'],'progress_verified':True,'bypass_confirmed':False,'stage_complete':False},Provenance('v2:replan',method='new_observed_target_then_verified_displacement'),.9,'verified')
                        deferred_pending=None
                    if result['kind']=='navigation' and not moved:
                        failures+=1;self.metrics['no_progress']+=1
                    else:
                        if failures:self.metrics['recoveries']+=1
                        failures=0
                    self.snapshot(session,task,'cycle',result)
                    if failures>=2:
                        self.metrics['replans']+=1
                        # Do not replay the same failed edge without new evidence.
                        self.memory.remember('episodic','failed_approach',session.scope,{'approach':'v2_local_edge','result':result,'run_id':session.run_id},Provenance('v2:navigation'),.9,'verified')
                    if failures>=4:raise RuntimeError('Four unverified movements including recovery; local route needs obstacle evidence')
                except (RuntimeError,ValueError) as error:
                    # A changed/unknown screen is inspected; it is never silently
                    # treated as a stage result or clicked through.
                    if session.last_features['scene']=='jogo':session.transition('pausa')
                    evidence=self.verify_completion()
                    if evidence:
                        root.state=task.state=State.COMPLETED;root.evidence.extend(evidence);task.evidence.extend(evidence)
                        self.memory.save_task(root);self.memory.save_task(task);self.memory.goal_state(self.runtime.goal_id,State.COMPLETED)
                        outcome='stage_complete';self.metrics['completed']=True
                        self.memory.remember('semantic','validated_strategy',session.scope,{'run_id':session.run_id,'initial_spawn_verified':start_verified,'result_evidence':evidence},Provenance('v2:stage_result',evidence_ids=evidence),.98,'verified')
                        break
                    reason=str(error);outcome='blocked'
                    category='perception_failures' if any(t in reason.lower() for t in ('not confidently located','marker absent','marker','unrecognized screen')) else 'navigation_failures'
                    self.metrics[category]+=1
                    try:
                        research=self.research_blocker(session,reason);self.snapshot(session,task,'blocker_research',research)
                        if self.metrics['frontier_deferrals']<3 and any(token in reason for token in ('Observed edge blocked','Four unverified movements')):
                            deferred=session.defer_current_frontier(reason)
                            if deferred:
                                self.metrics['frontier_deferrals']+=1
                                if deferred.get('next_target'):
                                    self.metrics['replans']+=1;deferred_pending={**deferred,'route_hypothesis':research.get('route_hypothesis')}
                                    self.snapshot(session,task,'frontier_deferred',deferred_pending)
                                    failures=0;outcome='budget_exhausted';reason='';continue
                        if research.get('solution') and self.metrics['puzzle_attempts']<1:
                            from .puzzle_control import BombRockController
                            self.metrics['puzzle_attempts']+=1
                            try:
                                session.transition('jogo')
                                puzzle=BombRockController(session,research['solution']).solve()
                                self.metrics['puzzle_verified']+=1;self.metrics['replans']+=1;self.metrics['recoveries']+=1
                                self.snapshot(session,task,'puzzle_resolved',puzzle)
                                failures=0;session.failed_count=0;outcome='budget_exhausted';reason=''
                                continue
                            except InterruptedError:raise
                            except Exception as puzzle_error:
                                reason+='; puzzle: '+str(puzzle_error);self.metrics['verification_failures']+=1
                                self.runtime.event('v2_puzzle_not_verified',reason=str(puzzle_error))
                            finally:
                                if session.last_features['scene']=='jogo':session.transition('pausa')
                    except InterruptedError:raise
                    except Exception as research_error:self.runtime.event('v2_research_failure',error=str(research_error))
                    break
            if outcome!='stage_complete':
                task.state=State.INTERRUPTED if self.bot.cancel.is_set() else State.BLOCKED
                root.state=task.state;self.memory.save_task(root)
                task.data['reason']=reason or outcome;self.memory.save_task(task);self.memory.goal_state(self.runtime.goal_id,task.state)
        except InterruptedError:
            outcome='interrupted';root.state=task.state=State.INTERRUPTED;self.memory.save_task(root);self.memory.save_task(task);self.memory.goal_state(self.runtime.goal_id,State.INTERRUPTED)
        except Exception as error:
            outcome='blocked';reason=type(error).__name__+': '+str(error)
            root.state=task.state=State.BLOCKED;task.data['reason']=reason
            self.memory.save_task(root);self.memory.save_task(task);self.memory.goal_state(self.runtime.goal_id,State.BLOCKED)
        finally:
            self.runtime.running=False
            try:
                if session.last_features and session.last_features['scene']=='jogo':session.transition('pausa')
            finally:
                report=session.close()
                report.update(kind='initial_stage_trial' if start_verified else 'resumed_stage_trial',outcome=outcome,reason=reason,initial_spawn_verified=start_verified,metrics=self.metrics,map_anchor_reference=getattr(session,'anchor_metadata',None))
                (session.folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                (self.root/'evaluations/v2/last-stage-trial.json').write_text(json.dumps({'folder':str(session.folder),**{k:v for k,v in report.items() if k!='actions'}},ensure_ascii=False,indent=2),encoding='utf-8')
                self.bot.observe()
        return report
