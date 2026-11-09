"""Walkthrough segments on the existing worker, task hierarchy and SQLite."""
import json,math,time
from ..contracts import State,Task,uid,Provenance
from ..stage_v2 import StageRunner
from .session import GameplaySession
from .walkthrough import WalkthroughPlanner,observed_mode

class StageV3Runner(StageRunner):
    @staticmethod
    def enemy_present(session,features):
        if not features.get('combat_present',features.get('enemy_count')):return False
        return session.preflight_enemy(features) if hasattr(session,'preflight_enemy') else True
    def __init__(self,bot,runtime,root):
        super().__init__(bot,runtime,root)
        self.planner=WalkthroughPlanner(self.root,self.memory,runtime.research)
        self.landmark_targets={}
        self.metrics.update(high_level_completed=0,segments=0,combats=0,guide_cache_hits=0,model_calls=0)
    def publish(self,session,step,result):
        self.runtime.last_decision='v3_'+step['id']
        self.bot.note='V3 · '+step['title']
        self.runtime.metrics.update(cycles=self.metrics['cycles'],actions=len(session.controls.actions),replans=self.metrics['replans'],model_calls=self.metrics['model_calls'],decision_ms=self.metrics['decision_ms'])
        row={'at':time.time(),'step_id':step['id'],'kind':step['kind'],'result':result,'frame':session.last_features['frame']}
        with (session.folder/'plan-execution.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        self.runtime.event('v3_plan_segment',data=row)
    def reconcile_pending_completion(self,initial):
        """Recover an observed exit after restart without issuing another input."""
        from types import SimpleNamespace
        from ..stage_v2 import completion_evidence
        from .exit_control import verify_exit_result
        if initial.scene not in ('resultado','mapa'):return None
        if initial.scene=='resultado' and not completion_evidence(getattr(self.bot,'snapshot',{})):return None
        scope='world:1:passage:1'
        pending=self.memory.retrieve(scope,kind='v3_exit_attempt',include_global=False,limit=1)
        saved=self.memory.retrieve(scope,kind='v3_active_plan',include_global=False,limit=1)
        if not pending or not saved or time.time()-pending[0]['updated']>3600:return None
        attempt=pending[0]['content'];active=saved[0]['content'];context=attempt.get('exit_context',{})
        if active.get('cursor')!=8 or context.get('entry_token')!=active.get('entry_token') or context.get('plan_id')!=active.get('plan_id') or not context.get('exit_interaction_issued'):return None
        folder=(self.root/'data/v3'/attempt['run_id']).resolve()
        if folder.parent!=(self.root/'data/v3').resolve():raise ValueError('Invalid pending exit evidence folder')
        def check_cancel():
            if self.bot.cancel.is_set():raise InterruptedError('Parado pelo usuário')
        session=SimpleNamespace(root=self.root,folder=folder,scope=scope,run_id=attempt['run_id'],memory=self.memory,check_cancel=check_cancel)
        result=verify_exit_result(session,self.runtime,self.bot,attempt['exit_landmark'],context)
        if not result:return None
        frame=result['result_observations'][-1]['frame']
        self.planner.checkpoint(active,{'id':'exit'},frame,True,result)
        tasks=self.memory.tasks(self.runtime.goal_id)
        for task in tasks:
            if task.kind=='complete_stage' or task.data.get('plan_id')==active['plan_id'] and task.data.get('step_id')=='exit':
                task.state=State.COMPLETED;task.evidence.extend(result['result_evidence']);self.memory.save_task(task)
        self.memory.goal_state(self.runtime.goal_id,State.COMPLETED)
        self.metrics.update(completed=True,high_level_completed=1)
        report={'kind':'v3_pending_exit_reconciliation','outcome':'stage_complete','run_id':attempt['run_id'],'metrics':self.metrics,'active_plan':active,'result':result,'game_inputs_sent':0,'original_trial_report_preserved':True}
        (folder/'exit-reconciliation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (self.root/'evaluations/v3/last-stage-trial.json').write_text(json.dumps({'folder':str(folder),**report},ensure_ascii=False,indent=2),encoding='utf-8')
        return report
    def final_corridor_segment(self,s,state,alignment,position,map_features,target_y):
        """Share the verified room/gate route between encounter and exit."""
        if 670<=position[1]<748:
            from .room_navigation import navigate_room
            return navigate_room(s,[405,755],tolerance=7,max_actions=12)
        if 748<=position[1]<813:
            from .lantern_gate import traverse_open_gate
            return traverse_open_gate(s)
        target=[425.5,680] if position[1]<670 else [425.5,target_y]
        checkpoint=(state,alignment,position,map_features,len(s.controls.actions));s.transition('jogo')
        return s.navigate_to(target,tolerance=7,allow_npc_bypass=True,_checkpoint=checkpoint)
    def execute_step(self,s,step,remaining):
        kind=step['kind']
        if kind=='navigate':
            result=s.navigate_to(step['target_reference'],step.get('tolerance',8),step.get('run',False),step.get('allow_npc_bypass',False))
            self.metrics['segments']+=1
            if result.get('reason')=='enemy_detected':
                combat=s.fight_continuously(min(60,remaining));self.metrics['combats']+=1
                if not combat['visible_combat_ended']:raise RuntimeError('Encounter interrupt not verified: '+combat['outcome'])
                return False,{'route_interrupt_combat':combat}
            if not result.get('verified') and not result.get('progress_verified'):raise RuntimeError('Route checkpoint diverged: '+result.get('reason','no progress'))
            return bool(result.get('verified')),result
        s.transition('jogo');features=getattr(s,'last_features',None)
        if not features or features.get('scene')!='jogo' or time.time()-features.get('at',0)>.35:_,features=s.capture('v3-objective-check')
        if features['scene']!='jogo':raise RuntimeError('Objective screen changed')
        if kind=='encounter':
            s.recover_item_after_combat=step.get('id')!='final_encounter'
            if step.get('id')=='final_encounter':
                active=self.memory.retrieve(s.scope,kind='v3_active_plan',include_global=False,limit=1)
                verified=self.memory.retrieve(s.scope,kind='v3_final_encounter_verified',include_global=False,limit=2)
                if active and any(r['validation']=='verified' and r['content'].get('entry_token')==active[0]['content'].get('entry_token') for r in verified):
                    return True,{'verified':True,'resumed_verified_encounter':verified[0]['id'],'source':verified[0]['content']}
                if getattr(s,'last_frame',None) is not None and getattr(s,'held_object_kind',None)!='brazier':
                    from .carry_combat import arrow_visible
                    if arrow_visible(s,s.last_frame):
                        from ..lantern_control import LanternController
                        LanternController(s).restore_held();features=s.last_features
            if self.enemy_present(s,features):
                result=s.fight_continuously(min(60,remaining),prior_enemy_evidence=features);self.metrics['combats']+=1
                if not result['visible_combat_ended']:raise RuntimeError('Combat not verified: '+result['outcome'])
                s.reconsider_frontiers('new_visible_combat');return True,result
            if step.get('id')=='final_encounter':
                recent=getattr(s,'last_confirmed_enemy',None)
                if recent and recent.get('scene')=='jogo' and recent.get('combat_present',recent.get('enemy_count')) and 0<=time.time()-recent.get('at',0)<10:
                    combat=s.fight_continuously(min(60,remaining),prior_enemy_evidence=recent);self.metrics['combats']+=1
                    if not combat['visible_combat_ended']:raise RuntimeError('Combat not verified: '+combat['outcome'])
                    return True,combat
                state,alignment,position,map_features=s.map_state('v3-final-encounter-route-map')
                if position[1]<931 or abs(position[0]-425.5)>9:
                    result=self.final_corridor_segment(s,state,alignment,position,map_features,938);self.metrics['segments']+=1
                    if result.get('reason')=='enemy_detected':
                        combat=s.fight_continuously(min(60,remaining));self.metrics['combats']+=1
                        if not combat['visible_combat_ended']:raise RuntimeError('Combat not verified: '+combat['outcome'])
                        return True,combat
                    if not result.get('verified') and not result.get('progress_verified'):raise RuntimeError('Final encounter approach did not progress')
                    return False,{'kind':'final_encounter_approach','result':result,'metrics':{'verified':True}}
                s.transition('jogo')
                for _ in range(4):
                    _,features=s.capture('v3-final-encounter-trigger')
                    if self.enemy_present(s,features):
                        result=s.fight_continuously(min(60,remaining),prior_enemy_evidence=features);self.metrics['combats']+=1
                        if not result['visible_combat_ended']:raise RuntimeError('Combat not verified: '+result['outcome'])
                        return True,result
                raise RuntimeError('Final encounter absent at the observed southern chamber; no unrelated frontier explored')
            if step.get('trigger_reference'):
                result=s.navigate_to(step['trigger_reference'],tolerance=5,allow_npc_bypass=True)
                if not result.get('verified') and result.get('reason')!='enemy_detected' and not result.get('progress_verified'):raise RuntimeError('Encounter trigger route diverged')
                s.transition('jogo')
                for _ in range(4):
                    _,features=s.capture('v3-encounter-trigger')
                    if self.enemy_present(s,features):
                        result=s.fight_continuously(min(60,remaining));self.metrics['combats']+=1
                        if not result['visible_combat_ended']:raise RuntimeError('Combat not verified: '+result['outcome'])
                        return True,result
                raise RuntimeError('Guide encounter absent at its observed trigger; checkpoint not advanced')
            result=s.navigate_once()
            if result.get('kind')=='combat':
                self.metrics['combats']+=1
                if not result['result']['visible_combat_ended']:raise RuntimeError('Combat not verified: '+result['result']['outcome'])
                return True,result
            return False,result
        if kind=='explore':
            objects={o['kind'] for o in features.get('puzzle_objects',[])};entities={e['kind'] for e in features.get('entities',[])}
            if step['landmark'].get('portable_brazier') and 'portable_brazier' in objects:
                s.transition('pausa');return True,{'landmark_observed':'portable_brazier','frame':features['frame']}
            if step['landmark'].get('rock_and_bomb_candidates'):
                if {'rock_obstacle_candidate','bomb_candidate'}<=entities:
                    s.transition('pausa');return True,{'landmark_observed':'rock_and_bomb_candidates','frame':features['frame']}
                if 'portable_brazier' in objects:
                    # The guide explicitly describes an alternative combat
                    # branch. Seeing its later landmark verifies that branch.
                    s.transition('pausa');return True,{'landmark_observed':'portable_brazier','adaptation':'later landmark reached by alternative branch','frame':features['frame']}
            if step['landmark'].get('portable_brazier') or step['id']=='west_and_junction':
                if 'portable_brazier' not in self.landmark_targets:
                    memories=self.memory.retrieve(s.scope,kind='v3_stage_landmark',include_global=False,limit=10)+self.memory.retrieve(s.scope,kind='v2_object_vantage',include_global=False,limit=50)
                    candidates=[m for m in memories if m['validation']=='verified' and m['content'].get('anchor_id')==s.map_anchor.identity and any(o['kind']=='portable_brazier' for o in m['content'].get('objects',[])) and 300<m['content'].get('actor_reference',[0,0])[0]<600 and 200<m['content'].get('actor_reference',[0,0])[1]<700]
                    self.landmark_targets['portable_brazier']=min(candidates,key=lambda m:m['content']['actor_reference'][1])['content'] if candidates else None
                vantage=self.landmark_targets['portable_brazier']
                if vantage:
                    result=s.navigate_to(vantage['actor_reference'],tolerance=10,allow_npc_bypass=True)
                    if result.get('already_at_checkpoint'):raise RuntimeError('Recorded brazier actor vantage reached but object not visible; guide landmark diverged')
                    if result.get('reason')=='enemy_detected':
                        combat=s.fight_continuously(min(60,remaining));self.metrics['combats']+=1
                        if not combat['visible_combat_ended']:raise RuntimeError('Combat not verified: '+combat['outcome'])
                    self.metrics['segments']+=1
                    return False,{'kind':'landmark_route','recorded_actor_vantage':vantage['actor_reference'],'metrics':{'verified':result.get('verified') or result.get('progress_verified',False)},'result':result}
            result=s.navigate_once(preferred_direction='left' if step['id']=='west_and_junction' else None);self.metrics['segments']+=result['kind']=='navigation';self.metrics['combats']+=result['kind']=='combat'
            return False,result
        if kind=='puzzle':
            if self.enemy_present(s,features):
                from .carry_combat import fight_with_carried_item
                result=fight_with_carried_item(s,min(60,remaining));self.metrics['combats']+=1
                if not result['visible_combat_ended']:raise RuntimeError('Combat not verified: '+result['outcome'])
                return False,{'puzzle_interrupted_by_encounter':result}
            from .puzzle import LanternSegment
            try:result=LanternSegment(s).run()
            except RuntimeError:
                current=s.last_features
                if current['scene']!='jogo' or not self.enemy_present(s,current):raise
                from .carry_combat import fight_with_carried_item
                combat=fight_with_carried_item(s,min(60,remaining));self.metrics['combats']+=1
                if not combat['visible_combat_ended']:raise RuntimeError('Combat not verified: '+combat['outcome'])
                return False,{'puzzle_interrupted_by_encounter':combat}
            return bool(result.get('verified')),result
        if kind=='exit':
            # Gameplay HUD was just verified above; screen changes are
            # independently checked for a real result by the outer runner.
            evidence=[]
            if evidence:return True,{'stage_complete':True,'result_evidence':evidence}
            map_state,alignment,position,map_features=s.map_state('v3-exit-route-map')
            if position[1]<930 or abs(position[0]-425.5)>9:
                # Use the live floor in the compact object room: the pause
                # marker can occlude its narrow map nodes near a pedestal.
                result=self.final_corridor_segment(s,map_state,alignment,position,map_features,938)
                if result.get('reason')=='enemy_detected':
                    combat=s.fight_continuously(min(60,remaining));self.metrics['combats']+=1
                    if not combat['visible_combat_ended']:raise RuntimeError('Combat not verified: '+combat['outcome'])
                    return False,{'route_interrupt_combat':combat}
                self.metrics['segments']+=1
                return False,result
            from .exit_control import exit_forward
            result=exit_forward(s,self.runtime,self.bot,position,map_features['frame'])
            return bool(result.get('stage_complete')),result
        raise RuntimeError('Unsupported typed stage objective')
    def run(self,max_steps=100,max_seconds=900,video=True):
        max_steps=min(150,max(1,int(max_steps)));max_seconds=min(1800,max(10,int(max_seconds)))
        self.runtime.open_goal('V3: execute the observed Passage 1 walkthrough with continuous controls')
        initial=self.runtime.environment.observe()
        for _ in range(2):
            if initial.scene!='carregando':break
            self.bot.cancel.wait(.2);initial=self.runtime.environment.observe()
        self.runtime.evidence(initial)
        recovered=self.reconcile_pending_completion(initial)
        if recovered:return recovered
        if initial.scope!='world:1:passage:1' or initial.scene!='pausa' or not initial.features.get('stage_observed'):raise RuntimeError('V3 requires the identified Passage 1 pause map')
        mode=observed_mode(initial)
        if not mode:raise RuntimeError('Current stage mode not observed; no walkthrough selected')
        root=[task for task in self.memory.tasks(self.runtime.goal_id) if task.kind=='complete_stage'][-1];root.scope=initial.scope;root.state=State.RUNNING;self.memory.save_task(root)
        try:s=GameplaySession(self.root,self.bot.adb,self.memory,self.bot.cancel,initial.scope,uid('v3_trial'),video=video)
        except Exception as exc:
            root.state=State.BLOCKED;self.memory.save_task(root);self.memory.goal_state(self.runtime.goal_id,State.BLOCKED);self.runtime.event('v3_backend_unavailable',error=str(exc),game_input_sent=False);raise
        s.frame_callback=getattr(self.bot,'publish_fast_frame',None);s.goal_id=self.runtime.goal_id;s.interaction_handler=self.interact
        outcome='budget_exhausted';reason='';start_verified=False;plan=None;active=None;task=None;failure_counts={};self.runtime.running=True;begun=time.perf_counter()
        try:
            state,_,_,_=s.map_state('v3-initial-map');start_verified=self.configure_map_reference(s,state,initial.scope)
            version=self.bot.adb.call('shell','dumpsys','package','com.kakaogames.gdts').decode(errors='replace')
            import re
            match=re.search(r'versionName=([^\s]+)',version);version=match[1] if match else 'unknown'
            plan=self.planner.ensure(initial.scope,mode,s.map_anchor.identity,version,self.runtime.goal_id);self.metrics['guide_cache_hits']+=int(plan['cache_hit'])
            tickets=self.memory.retrieve(initial.scope,kind='v2_prepared_spawn',include_global=False,limit=1)
            token=str(tickets[0]['content'].get('prepared_at')) if tickets and tickets[0]['validation']=='verified' else None
            active=self.planner.activate(plan,s.run_id,new_entry=start_verified,entry_token=token)
            (s.folder/'stage-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
            deadline=time.monotonic()+max_seconds
            for _ in range(max_steps):
                s.check_cancel()
                if time.monotonic()>=deadline:break
                if active['cursor']>=len(plan['steps']):
                    evidence=self.verify_completion()
                    if not evidence:raise RuntimeError('Plan exhausted without independent stage result evidence')
                    root.evidence.extend(evidence);outcome='stage_complete';self.metrics['completed']=True;break
                step=plan['steps'][active['cursor']]
                existing=[t for t in self.memory.tasks(self.runtime.goal_id) if t.data.get('plan_id')==plan['id'] and t.data.get('step_id')==step['id']]
                task=existing[-1] if existing else Task(uid('v3_step'),self.runtime.goal_id,'v3_'+step['kind'],step['title'],initial.scope,parent_id=root.id,success=step['checkpoint'],max_attempts=30,data={'plan_id':plan['id'],'step_id':step['id']})
                task.state=State.RUNNING;task.attempts+=1;self.memory.save_task(task);s.task_id=task.id;self.metrics['cycles']+=1;cycle=time.perf_counter()
                try:
                    completed,result=self.execute_step(s,step,deadline-time.monotonic());self.metrics['cycle_ms'].append((time.perf_counter()-cycle)*1000);self.publish(s,step,result)
                    if result.get('puzzle_interrupted_by_encounter',{}).get('visible_combat_ended'):failure_counts[step['id']]=0
                    if result.get('stage_complete'):
                        root.evidence.extend(result['result_evidence']);outcome='stage_complete';self.metrics['completed']=True
                    if completed:
                        self.planner.checkpoint(active,step,s.last_features['frame'],True,result);task.state=State.COMPLETED;self.metrics['high_level_completed']+=1
                    elif result.get('metrics',{}).get('verified') is False:
                        failure_counts[step['id']]=failure_counts.get(step['id'],0)+1
                        if failure_counts[step['id']]>=2:
                            deferred=s.defer_current_frontier('V3 repeated observed endpoint did not progress');self.metrics['replans']+=1
                            if not deferred or not deferred.get('next_target'):raise RuntimeError('No alternative observed frontier after two failed approaches')
                    self.memory.save_task(task)
                    if outcome=='stage_complete':break
                except (RuntimeError,ValueError) as exc:
                    if hasattr(s,'failure_checkpoint'):s.failure_checkpoint(str(exc))
                    evidence=self.verify_completion()
                    if evidence:root.evidence.extend(evidence);outcome='stage_complete';self.metrics['completed']=True;break
                    self.planner.divergence(plan,active,step,str(exc),s.last_features['frame']);self.metrics['replans']+=1
                    failure_counts[step['id']]=failure_counts.get(step['id'],0)+1
                    if failure_counts[step['id']]>=2 or 'Combat not verified' in str(exc):raise
                    # Recompute from the new aligned map once. Do not research
                    # again or replay a guessed movement through an obstacle.
                    if s.last_features['scene']=='jogo':s.transition('pausa')
            root.state=State.COMPLETED if self.metrics['completed'] else State.INTERRUPTED
        except InterruptedError:outcome='interrupted';root.state=State.INTERRUPTED
        except Exception as exc:outcome='blocked';reason=type(exc).__name__+': '+str(exc);root.state=State.BLOCKED
        finally:
            self.runtime.running=False
            if task and task.state!=State.COMPLETED:task.state=root.state;task.data['reason']=reason or outcome;self.memory.save_task(task)
            self.memory.save_task(root);self.memory.goal_state(self.runtime.goal_id,root.state)
            try:
                s.backend.release_all()
                if outcome!='stage_complete' and s.last_features and s.last_features['scene']=='jogo':s.transition('pausa')
            except Exception as exc:reason+='; final pause: '+str(exc)
            report=s.close();report.update(kind='v3_initial_stage_trial' if start_verified else 'v3_resumed_stage_trial',outcome=outcome,reason=reason,initial_spawn_verified=start_verified,metrics=self.metrics,active_plan=active,stage_plan_id=plan['id'] if plan else None,seconds_total=time.perf_counter()-begun)
            (s.folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            (self.root/'evaluations/v3/last-stage-trial.json').write_text(json.dumps({'folder':str(s.folder),'outcome':outcome,'reason':reason,'metrics':self.metrics,'active_plan':active},ensure_ascii=False,indent=2),encoding='utf-8')
        return report
