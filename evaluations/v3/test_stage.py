from types import SimpleNamespace
import unittest
from cognitive.v3.stage import StageV3Runner
from cognitive.runtime import CognitiveRuntime
from cognitive.contracts import Observation,State,uid
from cognitive.memory import Memory
from unittest.mock import patch
import tempfile,threading
from pathlib import Path

class StageTests(unittest.TestCase):
    def test_real_hierarchy_and_cursor_do_not_replace_stage_result_evidence(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'data/v3') as folder:
            root=Path(folder);(root/'evaluations/v3').mkdir(parents=True);memory=Memory(root/'memory.sqlite')
            ob=Observation(uid('simulation'),1,'pausa',.95,'world:1:passage:1','world:1:passage:1','Passagem 1 Normal',{'stage_observed':True})
            runtime=CognitiveRuntime(SimpleNamespace(observe=lambda:ob),memory)
            bot=SimpleNamespace(adb=SimpleNamespace(call=lambda *a:b'versionName=simulation'),cancel=threading.Event(),note='')
            runner=StageV3Runner(bot,runtime,root);plan={'id':'simulation-plan','scope':ob.scope,'mode':'normal','steps':[{'id':'corridor','kind':'navigate','title':'corridor','target_reference':[1,2],'checkpoint':{'endpoint':[1,2]}}],'cache_hit':True}
            runner.planner.ensure=lambda *a:plan;runner.verify_completion=lambda:[];runner.configure_map_reference=lambda *a:True
            class Session:
                def __init__(self,*a,**k):
                    self.run_id='simulation';self.folder=root/'data/v3/simulation';self.folder.mkdir(parents=True);self.map_anchor=SimpleNamespace(identity='simulation');self.controls=SimpleNamespace(actions=[]);self.last_features={'scene':'pausa','frame':'synthetic:map'};self.backend=SimpleNamespace(release_all=lambda:None)
                def check_cancel(self):pass
                def map_state(self,*a):return {},{},[0,0],{}
                def navigate_to(self,*a):return {'verified':True,'reason':'duration_elapsed'}
                def close(self):return {'actions':[],'seconds':0}
            with patch('cognitive.v3.stage.GameplaySession',Session):report=runner.run(2,10,video=False)
            self.assertEqual(report['active_plan']['cursor'],1);self.assertEqual(report['outcome'],'blocked');self.assertFalse(report['metrics']['completed'])
            self.assertEqual([t for t in memory.tasks(runtime.goal_id) if t.kind=='complete_stage'][0].state,State.BLOCKED);memory.close()
    def test_segment_event_uses_the_existing_runtime_contract(self):
        runner=self.runner();runtime=CognitiveRuntime.__new__(CognitiveRuntime);runtime.event_path=None;runtime.goal_id='simulation';runtime.metrics={}
        runner.runtime=runtime;runner.bot=SimpleNamespace(note='');runner.metrics.update(cycles=1,replans=0,model_calls=0,decision_ms=[])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'data/v3') as folder:
            session=SimpleNamespace(controls=SimpleNamespace(actions=[]),last_features={'frame':'synthetic:checkpoint'},folder=Path(folder))
            runner.publish(session,{'id':'corridor','title':'corridor','kind':'navigate'},{'verified':True})
            self.assertTrue((session.folder/'plan-execution.jsonl').exists())
    def runner(self):
        runner=StageV3Runner.__new__(StageV3Runner);runner.metrics={'segments':0,'combats':0}
        runner.verify_completion=lambda:[]
        return runner
    def test_gate_endpoint_tolerance_advances_to_final_chamber_instead_of_zero_action_loop(self):
        import time
        calls=[];runner=self.runner();f={'scene':'jogo','frame':'synthetic:game','at':time.time()}
        session=SimpleNamespace(last_features=f,transition=lambda *a:None,capture=lambda *a:(None,f),map_state=lambda *a:({}, {},[438.7,819.3],{'frame':'synthetic:map','at':time.time()}),controls=SimpleNamespace(actions=[]),navigate_to=lambda target,**kw:(calls.append(target) or {'verified':True}))
        complete,result=runner.execute_step(session,{'kind':'exit','id':'exit'},30);self.assertFalse(complete);self.assertEqual(calls,[[425.5,938]])
    def test_exit_lateral_detour_does_not_restart_the_route_north_of_current_progress(self):
        import time
        runner=self.runner();runner.runtime=None;runner.bot=None;f={'scene':'jogo','frame':'synthetic:game','at':time.time()};calls=[]
        s=SimpleNamespace(last_features=f,transition=lambda *a:None,map_state=lambda *a:({}, {},[440,988],{'frame':'synthetic:map'}),controls=SimpleNamespace(actions=[]),navigate_to=lambda target,**kw:(_ for _ in ()).throw(AssertionError('No northbound restart after a legitimate flank detour')))
        with patch('cognitive.v3.exit_control.exit_forward',side_effect=lambda *a:(calls.append(a[3]) or {'stage_complete':False})):
            done,result=runner.execute_step(s,{'kind':'exit','id':'exit'},30)
        self.assertFalse(done);self.assertEqual(calls,[[440,988]])
    def test_exit_large_lateral_correction_keeps_current_forward_height(self):
        import time
        runner=self.runner();f={'scene':'jogo','frame':'synthetic:game','at':time.time()};calls=[]
        s=SimpleNamespace(last_features=f,transition=lambda *a:None,map_state=lambda *a:({}, {},[470,988],{'frame':'synthetic:map'}),controls=SimpleNamespace(actions=[]),navigate_to=lambda target,**kw:(calls.append(target) or {'verified':True}))
        done,result=runner.execute_step(s,{'kind':'exit','id':'exit'},30);self.assertFalse(done);self.assertEqual(calls,[[425.5,988]])
    def test_known_route_executes_a_segment_without_model_or_microsteps(self):
        calls=[];runner=self.runner()
        s=SimpleNamespace(navigate_to=lambda *a:(calls.append(a) or {'verified':True,'reason':'duration_elapsed'}))
        complete,result=runner.execute_step(s,{'kind':'navigate','target_reference':[100,200],'title':'corridor'},30)
        self.assertTrue(complete);self.assertEqual(len(calls),1);self.assertEqual(runner.metrics['segments'],1)
    def test_final_encounter_without_visible_enemy_follows_south_route_not_frontier(self):
        import time
        runner=self.runner();runner.memory=SimpleNamespace(retrieve=lambda *a,**kw:[]);calls=[];f={'scene':'jogo','at':time.time(),'frame':'synthetic:game','enemy_count':0}
        def frontier(*a,**kw):raise AssertionError('No unrelated frontier may be explored before final encounter')
        s=SimpleNamespace(scope='world:1:passage:1',last_features=f,last_frame=None,last_confirmed_enemy={'scene':'jogo','combat_present':True,'at':time.time()-11,'frame':'synthetic:stale'},transition=lambda *a:None,map_state=lambda *a:({}, {},[439,819],{'frame':'synthetic:map','at':time.time()}),controls=SimpleNamespace(actions=[]),navigate_once=frontier,navigate_to=lambda target,**kw:(calls.append(target) or {'verified':True}))
        completed,result=runner.execute_step(s,{'id':'final_encounter','kind':'encounter'},30)
        self.assertFalse(completed);self.assertEqual(calls,[[425.5,938]]);self.assertEqual(result['kind'],'final_encounter_approach');self.assertFalse(s.recover_item_after_combat)
    def test_final_encounter_uses_recent_confirmed_presence_when_npc_finishes_during_pause(self):
        import time
        runner=self.runner();runner.memory=SimpleNamespace(retrieve=lambda *a,**kw:[]);calls=[];f={'scene':'jogo','at':time.time(),'frame':'synthetic:current-absence','enemy_count':0};prior={'scene':'jogo','at':time.time()-2,'frame':'synthetic:confirmed-enemy','combat_present':True}
        def fight(seconds,**kwargs):calls.append(kwargs);return {'visible_combat_ended':True,'clear_frames':['synthetic:a','synthetic:b','synthetic:c'],'raw_confirmation':'synthetic:raw'}
        s=SimpleNamespace(scope='world:1:passage:1',last_features=f,last_frame=None,last_confirmed_enemy=prior,transition=lambda *a:None,fight_continuously=fight)
        completed,result=runner.execute_step(s,{'id':'final_encounter','kind':'encounter'},30)
        self.assertTrue(completed);self.assertIs(calls[0]['prior_enemy_evidence'],prior);self.assertEqual(len(result['clear_frames']),3)
    def test_final_chamber_absence_cannot_complete_or_send_unrelated_navigation(self):
        import time
        runner=self.runner();runner.memory=SimpleNamespace(retrieve=lambda *a,**kw:[]);f={'scene':'jogo','at':time.time(),'frame':'synthetic:game','enemy_count':0};seen=[]
        s=SimpleNamespace(scope='world:1:passage:1',last_features=f,last_frame=None,transition=lambda *a:None,map_state=lambda *a:({}, {},[425.5,937.7],{'frame':'synthetic:map'}),capture=lambda label:(seen.append(label) or None,f))
        with self.assertRaisesRegex(RuntimeError,'Final encounter absent'):runner.execute_step(s,{'id':'final_encounter','kind':'encounter'},30)
        self.assertEqual(len(seen),4)
    def test_revealed_map_uses_brazier_before_gate_instead_of_later_exit_torch(self):
        import time
        runner=self.runner();runner.landmark_targets={};calls=[]
        def vantage(y):return {'validation':'verified','content':{'anchor_id':'synthetic:anchor','actor_reference':[409,y],'objects':[{'kind':'portable_brazier'}]}}
        runner.memory=SimpleNamespace(retrieve=lambda *a,**kw:[vantage(936),vantage(684),vantage(311)])
        features={'scene':'jogo','at':time.time(),'frame':'synthetic:game','puzzle_objects':[],'entities':[]}
        session=SimpleNamespace(scope='world:1:passage:1',map_anchor=SimpleNamespace(identity='synthetic:anchor'),last_features=features,transition=lambda *a:None,navigate_to=lambda target,**kw:(calls.append((target,kw)) or {'verified':True}))
        complete,result=runner.execute_step(session,{'id':'west_and_junction','kind':'explore','landmark':{'rock_and_bomb_candidates':True}},30)
        self.assertFalse(complete);self.assertEqual(calls[0][0],[409,311]);self.assertNotIn('max_segment_ms',calls[0][1])
    def test_route_interrupt_combat_does_not_complete_route_checkpoint(self):
        runner=self.runner();s=SimpleNamespace(navigate_to=lambda *a:{'verified':False,'reason':'enemy_detected'},fight_continuously=lambda seconds:{'visible_combat_ended':True})
        complete,result=runner.execute_step(s,{'kind':'navigate','target_reference':[1,2]},30)
        self.assertFalse(complete);self.assertIn('route_interrupt_combat',result)
    def test_missing_expected_encounter_never_advances_plan(self):
        runner=self.runner();f={'scene':'jogo','enemy_count':0};s=SimpleNamespace(transition=lambda *a:None,capture=lambda *a:(None,f),navigate_to=lambda *a,**k:{'verified':True})
        with self.assertRaisesRegex(RuntimeError,'encounter absent'):runner.execute_step(s,{'kind':'encounter','trigger_reference':[1,2]},30)
    def test_alternative_branch_requires_a_current_later_landmark(self):
        runner=self.runner();f={'scene':'jogo','enemy_count':0,'puzzle_objects':[{'kind':'portable_brazier'}],'entities':[],'frame':'synthetic:room'}
        s=SimpleNamespace(transition=lambda *a:None,capture=lambda *a:(None,f))
        complete,result=runner.execute_step(s,{'kind':'explore','landmark':{'rock_and_bomb_candidates':True}},30)
        self.assertTrue(complete);self.assertIn('adaptation',result)
