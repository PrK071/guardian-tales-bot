from __future__ import annotations
from dataclasses import asdict
import math
from .contracts import Action, Observation, State, Task, Verdict, uid
from .perception import distance

def route_approach(route): return 'route:'+route['id']+('@'+route['version'] if route.get('version') else '')

class StrategicPlanner:
    """High-level policy grounded in current evidence and contextual memory.

    An optional advisor can propose research, but cannot bypass perception,
    budgets, known failed approaches or the deterministic tactical controller.
    """
    def choose(self,ob: Observation,memories:list[dict],routes:list[dict],advice=None):
        failed={item['content'].get('approach') for item in memories if item['kind']=='failed_approach'}
        if ob.blocked: return {'strategy':'stop','reason':'Protected interface: '+ob.blocked}
        if 'interface_cycle' in failed:
            return {'strategy':'blocked' if any(m['kind']=='research' for m in memories) else 'research','reason':'Repeated interface cycle without stage progress; investigate instead of toggling menus'}
        if ob.confidence<.65 or ob.scene in ('desconhecida','carregando'):
            if 'stabilize' in failed: return {'strategy':'blocked','reason':'Perception remained uncertain after bounded observations'}
            return {'strategy':'inspect','reason':'Perception must stabilize before planning'}
        if not ob.stage or ob.features.get('stage_confidence',0)<.75:
            if 'identify_stage' in failed: return {'strategy':'blocked','reason':'Stage identification failed within its observation budget'}
            return {'strategy':'identify','reason':'Current stage identity needs direct visual confirmation'}
        if ob.scene=='resultado': return {'strategy':'verify_clear','reason':'Result screen must be confirmed in a second observation'}
        if ob.scene=='pausa':
            if 'resume_ui' in failed: return {'strategy':'blocked','reason':'The observed resume control could not be verified'}
            return {'strategy':'resume','reason':'Stage identified; resume through observed Continue control'}
        successful=[item for item in memories if item['validation']=='verified' and (item['kind']=='validated_strategy' or item['kind']=='strategy_outcome' and item['content'].get('progressed'))]
        if advice and advice.get('strategy')=='stop': return {'strategy':'blocked','reason':'Model recommends stopping: '+advice['reason']}
        if advice and advice.get('strategy')=='research' and not any(item['kind']=='research' for item in memories):
            return {'strategy':'research','reason':'Model requests grounded investigation: '+advice['reason']}
        if ob.features.get('enemy_count',0)>0:
            if 'combat' in failed or ob.features.get('health') is not None and ob.features['health']<.2:
                if any(item['kind']=='research' for item in memories): return {'strategy':'blocked','reason':'Combat recovery requires a grounded new tactic'}
                return {'strategy':'research','reason':'Combat approach failed or health is low; investigate recovery before retrying'}
            return {'strategy':'combat','reason':'Enemy bar observed; use bounded deterministic controller'}
        if advice and advice.get('strategy')=='inspect' and ob.scene=='jogo':
            inspected=any(m['kind']=='inspected_location' and m['content'].get('minimap')==ob.features.get('minimap') for m in memories)
            if not inspected:return {'strategy':'inspect_map','reason':'Model requests inspection; inspect the observed location through the stage map'}
        for route in routes:
            if route_approach(route) not in failed:
                return {'strategy':'known_route','reason':'Current checkpoint matches a scoped route', 'route':route,
                        'memory_reused':[entry['id'] for entry in successful if entry['content'].get('approach')==route_approach(route)]}
        reports=[m for m in memories if m['kind']=='research']
        if not reports and any(m['kind']=='research_attempt' and not m['content'].get('usable_sources') for m in memories):
            return {'strategy':'blocked','reason':'Previous investigation found no usable sources; wait for new evidence instead of repeating requests'}
        if advice and advice.get('strategy')=='research' and not reports:
            return {'strategy':'research','reason':'Advisor identifies an evidence gap: '+advice['reason']}
        if not reports: return {'strategy':'research','reason':'No validated continuation available at this location'}
        return {'strategy':'blocked','reason':'References exist, but no grounded executable continuation; avoid inventing a route'}

class TaskPlanner:
    def task(self,goal_id,kind,title,scope,success,dependencies=None,parent_id=None,data=None,max_attempts=3,preconditions=None):
        task=Task(uid('task'),goal_id,kind,title,scope,parent_id=parent_id,success=success,
                  dependencies=dependencies or [],data=data or {},max_attempts=max_attempts,
                  preconditions=preconditions or {'minimum_confidence':0 if kind in ('identify_stage','stabilize') else .65,'not_blocked':True})
        task.validate(); return task
    def decompose(self,goal_id,ob: Observation,decision,root_id):
        strategy=decision['strategy']; scope=ob.scope
        if strategy=='identify':
            return [self.task(goal_id,'identify_stage','Identify current stage using the visible stage map',scope,{'stage_observed':True},parent_id=root_id,max_attempts=2)]
        if strategy=='inspect':
            return [self.task(goal_id,'stabilize','Obtain an identifiable observation',scope,{'confidence_at_least':.65},parent_id=root_id,max_attempts=3)]
        if strategy=='inspect_map':
            return [self.task(goal_id,'inspect_map','Inspect the current stage map for the current location',scope,{'stage_observed':True},parent_id=root_id,max_attempts=2)]
        if strategy=='resume':
            return [self.task(goal_id,'resume_ui','Resume the identified stage',scope,{'scene':'jogo'},parent_id=root_id,max_attempts=2)]
        if strategy=='verify_clear':
            return [self.task(goal_id,'verify_clear','Confirm the stage clear result',scope,{'stage_cleared_confirmations':2},parent_id=root_id,max_attempts=3)]
        if strategy=='combat':
            return [self.task(goal_id,'combat','Eliminate the currently observed enemies',scope,{'no_enemies_confirmations':2},parent_id=root_id,max_attempts=12)]
        if strategy=='research':
            investigation=self.task(goal_id,'research','Investigate the missing stage route or prerequisite',scope,{'usable_sources':1},parent_id=root_id,max_attempts=2,data={'problem':'progression obstacles route'})
            if ob.scene=='jogo':
                pause=self.task(goal_id,'inspect_map','Pause and identify the map before network research',scope,{'stage_observed':True},parent_id=root_id,max_attempts=1)
                investigation.dependencies=[pause.id];return [pause,investigation]
            return [investigation]
        if strategy=='known_route':
            route=decision['route']
            parent=self.task(goal_id,'segment','Reach the validated end of '+route['id'],scope,
                {'checkpoint':route.get('end_anchor')},parent_id=root_id,data={'approach':route_approach(route),'route_id':route['id']},max_attempts=1)
            tasks=[parent]; previous=None
            steps=[step for step in route['steps'] if step['op']!='pause']
            for i,step in enumerate(steps):
                if step['op'] in ('combat','wait_scene'): raise ValueError('Legacy composite steps need explicit cognitive decomposition')
                next_anchor=steps[i+1].get('anchor') if i+1<len(steps) else route.get('end_anchor')
                tasks.append(self.task(goal_id,'route_step',f'{route["id"]}: step {i+1}',scope,
                    {'checkpoint':next_anchor} if next_anchor else {'movement_observed':True},
                    dependencies=[previous] if previous else [],parent_id=parent.id,
                    data={'action':step,'approach':route_approach(route),'index':i},max_attempts=1))
                previous=tasks[-1].id
            if not route.get('end_anchor'): raise ValueError('Autonomous route requires an explicit endpoint checkpoint')
            return tasks
        return []
    def ready(self,tasks):
        states={task.id:task.state for task in tasks}
        for task in sorted(tasks,key=lambda item:item.kind!='identify_stage'):
            if task.kind in ('complete_stage','segment'): continue
            if task.state not in (State.PENDING,State.INTERRUPTED): continue
            if all(states.get(dep)==State.COMPLETED for dep in task.dependencies): return task
        return None
    def preconditions_met(self,task,ob,tasks):
        if ob.confidence<task.preconditions.get('minimum_confidence',.65): return False,'Perception confidence is below the task prerequisite'
        if task.preconditions.get('not_blocked') and ob.blocked: return False,'Protected interface'
        if task.preconditions.get('scene') and task.preconditions['scene']!=ob.scene: return False,'Interface prerequisite changed'
        states={item.id:item.state for item in tasks}
        if any(states.get(dep)!=State.COMPLETED for dep in task.dependencies): return False,'Task dependency is not completed'
        if task.kind in ('combat','route_step') and ob.scene!='jogo': return False,'Gameplay task requires the in-stage HUD'
        return True,None

class TacticalController:
    def action(self,task: Task,ob: Observation) -> Action:
        if task.kind=='identify_stage':
            return Action('observe') if ob.features.get('stage_observed') else Action('tap',{'x':.106,'y':.13},'Open the stage map') if ob.scene=='jogo' else Action('observe')
        if task.kind in ('inspect_map','safe_pause'):return Action('tap',{'x':.106,'y':.13},'Open the map for inspection or safe waiting')
        if task.kind=='resume_ui': return Action('text',{'text':'Continuar'},'Resume via an exact observed OCR target')
        if task.kind in ('stabilize','verify_clear'): return Action('observe')
        if task.kind=='route_step':
            step=dict(task.data['action']); op=step.pop('op'); step.pop('message',None)
            return Action(op,step,'Execute a checkpoint-guarded route step')
        if task.kind=='combat':
            enemy=ob.features.get('enemy')
            if not enemy: return Action('observe')
            if ob.features.get('health') is not None and ob.features['health']<.2: raise RuntimeError('Low health: tactical recovery required')
            x,y=enemy; dx=x-.5; dy=y-.5
            if math.hypot(dx,dy)>.10:
                direction=('down' if dy>0 else 'up') if abs(dy)>1.5*abs(dx) else ('right' if dx>0 else 'left') if abs(dx)>1.5*abs(dy) else ('down' if dy>0 else 'up')+'_'+('right' if dx>0 else 'left')
                return Action('move',{'direction':direction,'ms':250},'Approach the observed enemy, then observe again')
            return Action('attack',{'ms':600},'Attack in short bounded bursts')
        raise ValueError('No tactical action for '+task.kind)

class Reflector:
    def verify(self,task:Task,before:Observation,after:Observation,action:Action,checkpoint_match=False):
        evidence=[before.id,after.id]
        if after.blocked: return Verdict(False,False,'execution','Protected interface appeared',evidence,.99)
        if before.stage and after.stage and before.stage!=after.stage and after.scene!='resultado':
            return Verdict(False,False,'perception','Stage changed unexpectedly; reconcile context',evidence,.95)
        if after.confidence<.65 or after.scene in ('desconhecida','carregando'):
            return Verdict(False,False,'perception','Outcome could not be identified',evidence,.5)
        completed=False; reason='No verified task outcome'
        if 'stage_observed' in task.success:
            completed=bool(after.features.get('stage_observed')); reason='Stage label read from current screen'
        elif 'scene' in task.success:
            completed=after.scene==task.success['scene']; reason='Expected interface transition observed'
        elif 'confidence_at_least' in task.success:
            completed=after.confidence>=task.success['confidence_at_least']; reason='Perception stabilized'
        elif 'checkpoint' in task.success:
            completed=bool(checkpoint_match); reason='Endpoint checkpoint comparison'
        elif 'no_enemies_confirmations' in task.success:
            clear=after.scene=='jogo' and after.features.get('enemy_count')==0
            task.data['clear_count']=task.data.get('clear_count',0)+1 if clear else 0
            completed=task.data['clear_count']>=task.success['no_enemies_confirmations']; reason='Enemy absence checked across observations'
        elif 'stage_cleared_confirmations' in task.success:
            clear=after.features.get('stage_cleared') and after.stage==task.scope
            task.data['clear_count']=task.data.get('clear_count',0)+1 if clear else 0
            completed=task.data['clear_count']>=task.success['stage_cleared_confirmations']; reason='Stage result corroborated across observations'
        elif 'movement_observed' in task.success:
            completed=action.op=='move' and distance(before,after)>.018 and after.scene=='jogo'; reason='Visible local movement, not proof of stage completion'
        progressed=completed or (before.scene!=after.scene and after.scene!='desconhecida') or (before.features.get('enemy_count',0)>after.features.get('enemy_count',0))
        if action.op=='move' and distance(before,after)>.018: progressed=True
        failure=None if progressed else 'planning'
        return Verdict(progressed,completed,failure,reason if progressed else 'No evidence of progress: '+reason,evidence,.9 if completed else .65)
    def reconcile(self,saved:Observation,current:Observation,uncertain_operations):
        if current.blocked: return 'blocked','Protected interface must not be replayed'
        if not current.stage or current.features.get('stage_confidence',0)<.75: return 'identify','Fresh stage identity required after process restart'
        if saved.stage and saved.stage!=current.stage: return 'replan','Saved stage differs from live stage'
        if uncertain_operations: return 'uncertain','Prior command may have taken effect; verify its success criterion before resuming'
        if saved.scene==current.scene and distance(saved,current)<.035: return 'matched','Fresh scene and visual checkpoint match'
        return 'replan','Live interface or location differs; invalidate pending location-sensitive actions'
