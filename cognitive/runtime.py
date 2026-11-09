from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import hashlib, json, re, threading, time
from .contracts import Action, Observation, Provenance, State, Task, Verdict, now, uid
from .memory import Memory, encode
from .planning import StrategicPlanner, TaskPlanner, TacticalController, Reflector
from .research import ResearchEngine
from .advisor import HttpAdvisor

class CognitiveRuntime:
    def __init__(self,environment,memory:Memory,research=None,advisor=None,event_path=None):
        self.environment=environment; self.memory=memory
        self.research=research; self.advisor=advisor or HttpAdvisor()
        self.strategic=StrategicPlanner(); self.tasks=TaskPlanner(); self.tactical=TacticalController(); self.reflector=Reflector()
        self.owner=uid('executor'); self.goal_id=None; self.reconcile_needed=True
        self.event_path=Path(event_path) if event_path else None
        self.recent=[];self.state_history=[]; self.metrics={'cycles':0,'actions':0,'researches':0,'replans':0,'failures':0,'memory_reuses':0,'decision_ms':[], 'input_tokens':0,'output_tokens':0,'model_calls':0}
        self.current=None; self.last_decision=None; self.running=False
    def event(self,kind,**payload):
        item={'at':now(),'kind':kind,'goal_id':self.goal_id,**payload}
        if self.event_path:
            with self.event_path.open('a',encoding='utf-8') as file: file.write(encode(item)+'\n')
        return item
    def open_goal(self,title='Complete Guardian Tales Story'):
        if not isinstance(title,str) or not 1<=len(title)<=200: raise ValueError('Invalid goal title')
        self.goal_id=self.memory.goal(title)
        if not self.memory.tasks(self.goal_id):
            self.memory.save_task(self.tasks.task(self.goal_id,'complete_stage','Complete the current stage with observed clear evidence','unknown',{'stage_cleared_confirmations':2},max_attempts=100))
        return self.goal_id
    def evidence(self,ob):
        self.memory.observe(ob); self.current=ob
        self.memory.remember('working','current_state',ob.scope,{'goal_id':self.goal_id,'observation_id':ob.id,'scene':ob.scene,'stage':ob.stage,'features':ob.features},
                             ob.provenance,ob.confidence,'verified' if ob.features.get('stage_observed') else 'uncertain',dedupe='working:'+self.goal_id)
    def import_library(self,path):
        path=Path(path)
        if not path.exists(): return 0
        library=json.loads(path.read_text(encoding='utf-8')); count=0
        for world in library.get('worlds',[]):
            scope=f'world:{world["id"]}'
            for index,stage in enumerate(world.get('stages',[])):
                match=re.match(r'(\d+)-(\d+)',stage.get('title',''))
                passage=re.match(r'Passagem\s+(\d+)',stage.get('title',''),re.I)
                stage_scope=f'world:{world["id"]}:passage:{passage[1]}' if passage else f'world:{match[1]}:stage:{match[2]}' if match else scope
                self.memory.remember('semantic','guide',stage_scope,stage,Provenance(str(path),method='legacy_catalog_import'),.45,'reported',dedupe=f'library:{world["id"]}:{index}'); count+=1
        return count
    def context(self,ob):
        memories=[]
        for kind,limit in (('failed_approach',5),('validated_strategy',3),('inspected_location',2),('research',3),('research_attempt',2),('strategy_outcome',3)):
            memories.extend(self.memory.retrieve(ob.scope,kind=kind,limit=limit))
        # Also retrieve world-level semantics without unrelated stage histories.
        if ob.stage:
            world_scope=':'.join(ob.scope.split(':')[:2])
            if world_scope!=ob.scope:
                ids={item['id'] for item in memories}
                memories.extend(item for item in self.memory.retrieve(world_scope,category='semantic',limit=3) if item['id'] not in ids)
        return memories[:19]
    def reconcile(self,current):
        checkpoint=self.memory.load_checkpoint(self.goal_id)
        if not checkpoint: self.reconcile_needed=False; return
        saved=self.memory.observation(checkpoint['observation_id'])
        self.state_history=checkpoint['data'].get('state_history',[])[-6:]
        unresolved=self.memory.unresolved(self.goal_id)
        status,reason=self.reflector.reconcile(saved,current,unresolved)
        self.event('reconcile',status=status,reason=reason,saved=saved.id,current=current.id)
        self.memory.remember('episodic','reconciliation',current.scope,{'status':status,'reason':reason,'uncertain_operations':[item['id'] for item in unresolved]},
                             Provenance('runtime:reconcile',evidence_ids=[saved.id,current.id]),.95,'verified')
        if status=='identify': return
        all_tasks=self.memory.tasks(self.goal_id); by_id={task.id:task for task in all_tasks}
        for operation in unresolved:
            task=by_id.get(operation['task_id']); anchor=task.success.get('checkpoint') if task else None
            compatible=bool(task and task.scope in ('unknown',current.scope))
            confirmed=bool(compatible and anchor and self.match(current,anchor))
            if compatible and not confirmed and not anchor:
                before=self.memory.observation(operation['before_id'])
                try:
                    action=Action(**json.loads(operation['action']))
                    confirmed=self.reflector.verify(task,before,current,action).completed
                except (TypeError,ValueError,KeyError):confirmed=False
            if confirmed:
                task.state=State.COMPLETED; task.evidence.append(current.id); self.memory.save_task(task)
                self.memory.operation(operation['id'],'observed',current.id,{'recovered':True,'completed':True})
            else:
                self.memory.operation(operation['id'],'uncertain',current.id,{'recovery':'Do not repeat an operation whose outcome is unknown'})
                if task: task.state=State.REPLANNED; task.data['uncertain_operation']=operation['id']; self.memory.save_task(task)
        if status not in ('matched','identify'):
            for task in all_tasks:
                if task.kind=='route_step' and task.state in (State.PENDING,State.RUNNING,State.INTERRUPTED):
                    task.state=State.REPLANNED; task.data['invalidated_by_reconciliation']=current.id; self.memory.save_task(task)
        else:
            for task in all_tasks:
                if task.state==State.RUNNING: task.state=State.INTERRUPTED; self.memory.save_task(task)
        self.reconcile_needed=False
    def match(self,ob,anchor):
        return bool(anchor and hasattr(self.environment,'checkpoint_matches') and self.environment.checkpoint_matches(ob,anchor))
    def fail_approach(self,task,ob,reason,failure='planning'):
        approach=task.data.get('approach',task.kind)
        task.state=State.FAILED; task.data['failure_class']=failure; task.data['failure_reason']=reason; self.memory.save_task(task)
        self.memory.remember('episodic','failed_approach',ob.scope,{'approach':approach,'failure':failure,'reason':reason,'task_id':task.id},
                             Provenance('runtime:reflection',evidence_ids=[ob.id]),.9,'verified')
        for other in self.memory.tasks(self.goal_id):
            if other.parent_id==task.parent_id and other.kind=='route_step' and other.state==State.PENDING:
                other.state=State.REPLANNED; self.memory.save_task(other)
        self.metrics['replans']+=1
        self.event('replan',task_id=task.id,approach=approach,failure=failure,reason=reason)
    def plan(self,ob,root):
        planning_started=time.monotonic()
        context=self.context(ob); routes=self.environment.route_candidates(ob)
        advice=None
        # Never wait for a slow model while combat or hazards keep running.
        if self.advisor.available and ob.scene in ('pausa','entrada','mapa'):
            try:
                advice=self.advisor.advise({'observation':ob.to_dict(),'memories':context,'tasks':[task.to_dict() for task in self.memory.tasks(self.goal_id)[-12:]],'routes':[route['id'] for route in routes],'budget':{'remaining_model_calls':3-self.advisor.calls}})
                if advice:
                    self.metrics['model_calls']+=1; self.event('advisor_proposal',proposal=advice)
                    for field in ('input_tokens','output_tokens','cost_usd'):
                        values=[usage.get(field) for usage in self.advisor.usage]
                        self.metrics[field]=sum(values) if values and all(isinstance(value,(int,float)) for value in values) else None
                    if self.research and advice.get('claims'):
                        contradictions=self.research.compare_claims(advice['claims'])
                        if contradictions:
                            self.memory.remember('semantic','source_disagreement',ob.scope,contradictions,Provenance('advisor:unverified_claims'),.3,'uncertain')
            except InterruptedError:raise
            except Exception as error: self.event('advisor_failure',error=str(error)[:300])
            finally:self.metrics['model_calls']=self.advisor.calls
        decision=self.strategic.choose(ob,context,routes,advice)
        self.last_decision=decision['strategy']; self.event('strategic_plan',strategy=decision['strategy'],reason=decision['reason'],observation_id=ob.id,memory_ids=[item['id'] for item in context])
        self.metrics['decision_ms'].append(round((time.monotonic()-planning_started)*1000,3))
        self.metrics['memory_reuses']+=len(decision.get('memory_reused',[]))
        if decision['strategy'] in ('stop','blocked'):
            self.memory.goal_state(self.goal_id,State.BLOCKED)
            self.memory.remember('working','blocker',ob.scope,decision,Provenance('planner:strategic',evidence_ids=[ob.id]),.95,'verified',dedupe='blocker:'+self.goal_id)
            if ob.scene=='jogo' and ob.confidence>=.65:
                task=self.tasks.task(self.goal_id,'safe_pause','Pause gameplay before stopping on an unknown continuation',ob.scope,{'scene':'pausa'},parent_id=root.id,max_attempts=1,data={'stop_after':True})
                self.memory.save_task(task);return task
            return None
        tasks=self.tasks.decompose(self.goal_id,ob,decision,root.id)
        for task in tasks: self.memory.save_task(task)
        return self.tasks.ready(self.memory.tasks(self.goal_id))
    def step(self,cancel:threading.Event):
        started=time.monotonic(); self.metrics['cycles']+=1
        try:
            ob=self.environment.observe(); self.evidence(ob)
        except Exception as error:
            self.metrics['failures']+=1; self.event('perception_failure',error=str(error)[:300]); return 'perception_failure'
        if cancel.is_set(): return 'interrupted'
        if self.reconcile_needed: self.reconcile(ob)
        signature=json.dumps([ob.scene,ob.scope,ob.features.get('minimap')])
        self.state_history=(self.state_history+[signature])[-6:]
        if len(self.state_history)==6 and self.state_history[0]!=self.state_history[1] and self.state_history[0::2]==[self.state_history[0]]*3 and self.state_history[1::2]==[self.state_history[1]]*3:
            self.memory.remember('episodic','failed_approach',ob.scope,{'approach':'interface_cycle','failure':'planning','reason':'Alternating observations repeat without geographical or combat progress'},Provenance('runtime:cycle_detector',evidence_ids=[ob.id]),.9,'verified')
            self.metrics['replans']+=1;self.event('interface_cycle',state_history=self.state_history)
        tasks=self.memory.tasks(self.goal_id); roots=[task for task in tasks if task.kind=='complete_stage']; root=roots[-1]
        if root.state==State.COMPLETED:
            if ob.stage==root.scope and ob.scene=='resultado': return 'stage_complete'
            root=self.tasks.task(self.goal_id,'complete_stage','Complete the next current stage with observed clear evidence',ob.scope,{'stage_cleared_confirmations':2},max_attempts=100)
            self.memory.save_task(root); tasks=self.memory.tasks(self.goal_id)
        elif ob.stage and root.scope not in ('unknown',ob.scope) and ob.features.get('stage_confidence',0)>=.75:
            root.state=State.REPLANNED;root.data['replaced_by_stage']=ob.scope;self.memory.save_task(root)
            for previous in tasks:
                if previous.kind!='complete_stage' and previous.scope not in ('unknown',ob.scope) and previous.state in (State.PENDING,State.RUNNING,State.INTERRUPTED):
                    previous.state=State.REPLANNED;self.memory.save_task(previous)
            root=self.tasks.task(self.goal_id,'complete_stage','Complete the newly observed current stage',ob.scope,{'stage_cleared_confirmations':2},max_attempts=100)
            self.memory.save_task(root);tasks=self.memory.tasks(self.goal_id)
        if ob.stage and root.scope=='unknown': root.scope=ob.scope; self.memory.save_task(root)
        if ob.blocked:
            self.memory.goal_state(self.goal_id,State.BLOCKED); self.event('protected_ui',blocked=ob.blocked); return 'blocked'
        task=self.tasks.ready(tasks)
        if not ob.stage or ob.features.get('stage_confidence',0)<.75:
            if not task or task.kind!='identify_stage': task=self.plan(ob,root)
        # A directly observed stage identity can finish identification without an input.
        if task and task.kind=='identify_stage' and ob.features.get('stage_observed'):
            task.state=State.COMPLETED; task.evidence.append(ob.id); self.memory.save_task(task); return 'continued'
        if task and task.scope not in ('unknown',ob.scope) and task.kind!='identify_stage':
            self.fail_approach(task,ob,'Task scope differs from current stage','perception'); task=None
        if not task: task=self.plan(ob,root)
        if task is None: self.memory.checkpoint(self.goal_id,ob,{'reason':'planning_blocked'}); return 'blocked'
        ready,reason=self.tasks.preconditions_met(task,ob,self.memory.tasks(self.goal_id))
        if not ready:
            self.fail_approach(task,ob,reason,'perception'); return 'replan'
        if task.attempts>=task.max_attempts:
            self.fail_approach(task,ob,'Attempt budget exhausted'); return 'replan'
        if task.kind=='research':
            if not self.research:
                self.fail_approach(task,ob,'No working research provider configured','tool'); return 'blocked'
            task.attempts+=1; task.state=State.RUNNING; self.memory.save_task(task)
            try:
                report=self.research.investigate(ob.scope,task.data['problem'],self.goal_id)
                self.metrics['researches']+=1; task.data['research']=report
                task.state=State.COMPLETED if report['sources'] else State.BLOCKED
                task.evidence.append(ob.id); self.memory.save_task(task)
                self.event('research',query=report['query'],sources=[item['url'] for item in report['sources']],errors=report['errors'])
                self.memory.checkpoint(self.goal_id,ob,{'task_id':task.id,'research_cached':report.get('cached')})
                return 'continued' if report['sources'] else 'blocked'
            except Exception as error:
                self.fail_approach(task,ob,str(error),'tool'); return 'blocked'
        try: action=self.tactical.action(task,ob); action.validate()
        except Exception as error:
            self.fail_approach(task,ob,str(error),'planning'); return 'replan'
        if cancel.is_set(): return 'interrupted'
        task.state=State.RUNNING; task.attempts+=1; self.memory.save_task(task)
        operation=self.memory.prepare(self.goal_id,task.id,asdict(action),ob.id)
        self.memory.checkpoint(self.goal_id,ob,{'active_task_id':task.id,'operation_id':operation})
        # Journal issued BEFORE input. A crash from here is deliberately treated
        # as an uncertain effect rather than replaying the same command.
        self.memory.operation(operation,'issued')
        error=None
        try:
            self.environment.execute(action)
            if action.op!='observe': self.metrics['actions']+=1
        except InterruptedError:
            task.state=State.INTERRUPTED; self.memory.save_task(task)
            self.memory.operation(operation,'uncertain',result={'failure':'manual_stop'}); return 'interrupted'
        except Exception as exc: error=exc
        try:
            after=self.environment.observe(); self.evidence(after)
        except Exception as exc:
            self.metrics['failures']+=1; self.event('perception_failure',operation_id=operation,error=str(exc)[:300])
            self.memory.operation(operation,'uncertain',result={'failure':'perception','error':str(exc)[:300]})
            task.state=State.INTERRUPTED; self.memory.save_task(task); self.reconcile_needed=True; return 'perception_failure'
        if error:
            verdict=Verdict(False,False,'execution',str(error)[:300],[ob.id,after.id],.9)
        else:
            verdict=self.reflector.verify(task,ob,after,action,self.match(after,task.success.get('checkpoint')))
        self.memory.operation(operation,'observed',after.id,asdict(verdict))
        task.evidence.extend(verdict.evidence)
        task.state=State.COMPLETED if verdict.completed else State.PENDING
        self.memory.save_task(task)
        if task.state==State.COMPLETED and task.kind=='inspect_map':
            self.memory.remember('semantic','inspected_location',after.scope,{'minimap':ob.features.get('minimap'),'map_observation':after.id},Provenance('runtime:map_inspection',evidence_ids=[ob.id,after.id]),.9,'verified',dedupe='inspection:'+after.scope+':'+str(ob.features.get('minimap')))
        self.memory.remember('episodic','strategy_outcome',after.scope,{'task_id':task.id,'approach':task.data.get('approach',task.kind),'action':asdict(action),**asdict(verdict)},
                             Provenance('runtime:verify',evidence_ids=verdict.evidence),verdict.confidence,'verified' if verdict.completed else 'uncertain')
        self.event('verification',task_id=task.id,operation_id=operation,verdict=asdict(verdict),action=asdict(action))
        if not verdict.progressed:
            self.metrics['failures']+=1
            signature=(task.kind,action.op,json.dumps(action.args,sort_keys=True),after.features.get('visual_hash'))
            self.recent.append(signature); self.recent=self.recent[-6:]
            repeats=self.recent.count(signature)
            if task.attempts>=task.max_attempts or repeats>=2:
                self.fail_approach(task,after,verdict.reason,verdict.failure or 'planning')
        if task.state==State.COMPLETED and task.kind=='verify_clear':
            root.state=State.COMPLETED; root.evidence.extend(task.evidence); self.memory.save_task(root)
            # Complete CURRENT STAGE, never claim the entire story is cleared.
            self.event('stage_completed',stage=after.stage,evidence=task.evidence)
            self.memory.goal_state(self.goal_id,State.PENDING)
        if verdict.progressed and task.kind in ('route_step','combat'):self.state_history=[]
        self.finish_segments(after)
        self.memory.checkpoint(self.goal_id,after,{'last_task_id':task.id,'last_operation_id':operation,'last_verdict':asdict(verdict),'state_history':self.state_history})
        if task.data.get('stop_after'):return 'blocked'
        return 'continued' if verdict.progressed else 'replan'
    def finish_segments(self,ob):
        tasks=self.memory.tasks(self.goal_id)
        for segment in tasks:
            if segment.kind!='segment' or segment.state in (State.COMPLETED,State.FAILED): continue
            children=[task for task in tasks if task.parent_id==segment.id]
            if children and all(task.state==State.COMPLETED for task in children) and self.match(ob,segment.success.get('checkpoint')):
                segment.state=State.COMPLETED; segment.evidence.append(ob.id); self.memory.save_task(segment)
                self.memory.remember('semantic','validated_strategy',ob.scope,{'approach':segment.data['approach'],'end_anchor':segment.success['checkpoint'],'task_id':segment.id},
                                     Provenance('runtime:endpoint',evidence_ids=[ob.id]),.95,'verified',dedupe='validated:'+ob.scope+':'+segment.data['approach'])
    def run(self,title='Complete Guardian Tales Story',max_cycles=12,max_seconds=180,cancel=None):
        if isinstance(max_cycles,bool) or not isinstance(max_cycles,int) or isinstance(max_seconds,bool) or not isinstance(max_seconds,(int,float)) or not 1<=max_cycles<=100 or not 1<=max_seconds<=600: raise ValueError('Invalid runtime budget')
        cancel=cancel or threading.Event()
        self.open_goal(title)
        if not self.memory.acquire(self.owner,ttl=180): raise RuntimeError('Another cognitive executor owns the lease')
        self.running=True; self.reconcile_needed=True
        self.metrics={'cycles':0,'actions':0,'researches':0,'replans':0,'failures':0,'memory_reuses':0,'decision_ms':[],'cycle_ms':[], 'input_tokens':0,'output_tokens':0,'cost_usd':0,'model_calls':0}
        self.recent=[]
        self.state_history=[]
        if self.research: self.research.reset_budget()
        self.advisor.calls=0; deadline=time.monotonic()+max_seconds; outcome='budget_exhausted'
        if hasattr(self.advisor,'cancel'):self.advisor.cancel=cancel
        self.memory.goal_state(self.goal_id,State.RUNNING)
        try:
            for _ in range(max_cycles):
                if cancel.is_set(): outcome='interrupted'; break
                if time.monotonic()>=deadline: break
                if not self.memory.acquire(self.owner,ttl=180): raise RuntimeError('Executor lease lost')
                cycle_started=time.monotonic()
                try: outcome=self.step(cancel)
                except InterruptedError:outcome='interrupted'
                self.metrics['cycle_ms'].append(round((time.monotonic()-cycle_started)*1000,3))
                if outcome in ('blocked','interrupted','stage_complete'): break
                if outcome=='perception_failure' and self.metrics['failures']>=3: break
            if outcome not in ('blocked','interrupted','stage_complete'): outcome='budget_exhausted'
            self.memory.goal_state(self.goal_id,State.BLOCKED if outcome=='blocked' else State.INTERRUPTED)
            for task in self.memory.tasks(self.goal_id):
                if task.state==State.RUNNING: task.state=State.INTERRUPTED; self.memory.save_task(task)
            self.event('run_stopped',outcome=outcome,metrics=self.metrics)
            self.running=False
            return {'outcome':outcome,**self.status()}
        finally: self.running=False; self.memory.release(self.owner)
    def status(self):
        tasks=self.memory.tasks(self.goal_id) if self.goal_id else []
        return {'goal_id':self.goal_id,'running':self.running,'decision':self.last_decision,
                'current':self.current.to_dict() if self.current else None,'tasks':[task.to_dict() for task in tasks[-50:]],
                'goals':self.memory.goals(),'metrics':self.metrics,'memory':self.memory.summary(),
                'advisor':{'enabled':self.advisor.available,'backend':type(self.advisor).__name__,'usage':self.advisor.usage},
                'limitations':['No universal puzzle solver or full-story clear proof.','Text model proposals require grounded affordances; no VLM/video analysis.']}
