"""Reproducible V2 scenarios. Simulations never count as game completion."""
from pathlib import Path
import json,sys,tempfile,threading,time,unittest
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from cognitive.contracts import Action,Observation,Provenance,State,Task,uid,now
from cognitive.fast_control import FastSession
from cognitive.map_navigation import PauseMap
from cognitive.map_anchor import SpawnMapAnchor
from cognitive.memory import Memory
from cognitive.spatial import SpatialVision
from cognitive.stage_v2 import StageRunner,InteractionVision,compile_solution,completion_evidence
from cognitive.runtime import CognitiveRuntime

def map_state(block=False):
    floor=np.zeros((900,1600),np.uint8);floor[300:420,500:1050]=255
    if block:floor[:,760:800]=0
    return {'floor':floor,'player':[650.,360.],'bbox':[500,300,550,120]}

class V2Scenarios(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'data/v2');self.path=Path(self.tmp.name)
        self.memory=Memory(self.path/'memory.sqlite')
    def tearDown(self):
        self.memory.close();assert self.path.resolve().is_relative_to((ROOT/'data/v2').resolve());self.tmp.cleanup()
    def runner(self):return StageRunner(SimpleNamespace(cancel=threading.Event()),SimpleNamespace(memory=self.memory),ROOT)
    def test_01_simple_navigation(self):
        plan=PauseMap().next_motion(map_state(),[1000,360]);self.assertEqual(plan['direction'],'right')
        self.assertTrue(all(map_state()['floor'][int(y),int(x)] for x,y in plan['path']))
    def test_02_blocked_path(self):
        with self.assertRaisesRegex(ValueError,'No path'):PauseMap().path(map_state(True),[1000,360])
    def interaction(self,changed):
        before=cv2.imread(str(ROOT/'captures/1794088601124454200-before.png'));after=before.copy()
        if changed:cv2.rectangle(after,(500,160),(1050,280),(190,225,240),-1)
        class Session:
            scope='world:1:passage:1';last_frame=before;calls=0
            def capture(self,label):return self.last_frame,{}
            def pulse(self,action):
                action.validate();self.calls+=1
                self.last_frame=after if self.calls==1 else before
        session=Session();result=self.runner().interact(session)
        return result,session
    def test_03_interaction_success(self):
        result,session=self.interaction(True);self.assertTrue(result['verified']);self.assertEqual(session.calls,2)
    def test_04_interaction_no_effect(self):
        result,session=self.interaction(False);self.assertFalse(result['verified']);self.assertEqual(session.calls,1)
    def test_05_basic_combat(self):
        enemy={'kind':'enemy','bbox':[760,340,60,90]}
        frames=[{'scene':'jogo','health':1.,'player':[800,445],'entities':[enemy]}]+[{'scene':'jogo','health':1.,'player':[800,445],'entities':[]}]*3
        class Session:
            actions=[];scope='world:1:passage:1'
            def check_cancel(self):pass
            def capture(self,label):return None,frames.pop(0)
            def pulse(self,action,**kwargs):action.validate();self.actions.append(action)
        session=Session();session.memory=self.memory
        result=FastSession.fight(session,seconds=2)
        self.assertTrue(result['visible_combat_ended']);self.assertEqual(result['absent_observations'],3)
        self.assertEqual(session.actions[0].op,'attack')
        self.assertNotIn('stage_complete',result)
    def test_06_retrieved_puzzle(self):
        scope='world:1:passage:1';mid=self.memory.remember('semantic','research',scope,{'source':'fixture','snippet':'Pick a bomb and throw it at the rock'},Provenance('simulation:source'),.5,'reported')
        result=compile_solution(self.memory.retrieve(scope),scope,{'rock':True,'bomb':True})
        self.assertEqual(result['memory_id'],mid);self.assertEqual(result['validation'],'hypothesis');self.assertEqual(len(result['steps']),4)
        self.assertEqual(self.memory.retrieve(scope)[0]['validation'],'reported')
    def test_07_failed_move_replan(self):
        state=map_state();state['player']=[650.,400.]
        plan=PauseMap().recovery(state,'left');self.assertIsNotNone(plan);self.assertEqual(plan['direction'],'up')
        state['floor'][:]=0;self.assertIsNone(PauseMap().recovery(state,'left'))
    def test_08_restart_reconciliation(self):
        goal=self.memory.goal('V2 restart fixture');task=Task(uid('task'),goal,'v2_explore','Navigate','world:1:passage:1',state=State.RUNNING,success={'move_confirmed':True})
        self.memory.save_task(task);ob=Observation(uid('ob'),now(),'pausa',.95,task.scope,task.scope,'',{'scene':'pausa'},provenance=Provenance('simulation'))
        self.memory.checkpoint(goal,ob,{'v2':True,'next_action':'reobserve_not_replay'})
        operation=self.memory.prepare(goal,task.id,{'op':'move','args':{'direction':'left','ms':300}},ob.id);self.memory.operation(operation,'issued')
        self.memory.close();self.memory=Memory(self.path/'memory.sqlite')
        self.assertEqual(self.memory.load_checkpoint(goal)['data']['next_action'],'reobserve_not_replay')
        self.assertEqual(self.memory.unresolved(goal)[0]['state'],'issued')
        self.assertEqual(self.memory.tasks(goal)[0].state,State.RUNNING)
    def test_09_irrelevant_research(self):
        memories=[{'id':'unrelated','scope':'world:9:stage:1','validation':'reported','content':'bomb rock'}]
        self.assertIsNone(compile_solution(memories,'world:1:passage:1',{'rock':True,'bomb':True}))
        memories[0]['scope']='world:1:passage:1';self.assertIsNone(compile_solution(memories,memories[0]['scope'],{'rock':True,'bomb':False}))
    def test_10_false_completion(self):
        snap={'scene':'pausa','words':[{'text':'Continuar etapa concluída'}]};self.assertFalse(completion_evidence(snap))
        bot=SimpleNamespace(snapshot={});sequence=[{'scene':'resultado','words':[{'text':'Stage Clear'}]},{'scene':'jogo','words':[]}]
        class Environment:
            def observe(self):bot.snapshot=sequence.pop(0);return SimpleNamespace(id=uid('fixture'))
        runtime=SimpleNamespace(memory=self.memory,environment=Environment(),evidence=lambda ob:None)
        self.assertEqual(StageRunner(bot,runtime,ROOT).verify_completion(),[])

class HistoricalCaptures(unittest.TestCase):
    def test_dark_cave_edges_are_not_enemy_bars(self):
        for relative in ('data/v2/v2_trial_dfcf9912d4a94e9e/0010-combat-observe.jpg','data/v2/v2_trial_5aa90fc7327340cf/0046-before-move.jpg'):
            with self.subTest(frame=relative):self.assertEqual(SpatialVision().entities(cv2.imread(str(ROOT/relative)))['enemy_count'],0)
    def test_helmet_component_height_does_not_move_foot_to_head(self):
        frame=cv2.imread(str(ROOT/'data/v2/v2_trial_5aa90fc7327340cf/0118-before-pausa.jpg'))
        player=SpatialVision().entities(frame)['player'];self.assertIsNotNone(player);self.assertAlmostEqual(player[1],445,delta=8)
    def test_paused_health_reports_observed_damage(self):
        frame=cv2.imread(str(ROOT/'data/v2/pause-stability-0.png'))
        self.assertAlmostEqual(SpatialVision().entities(frame)['health'],.54,delta=.03)
    def test_jpeg_spawn_pin_keeps_observed_floor_below_it(self):
        state=PauseMap().parse(cv2.imread(str(ROOT/'data/v2/v2_trial_5aa90fc7327340cf/0000-initial.jpg')))
        self.assertGreaterEqual(state['bbox'][1]+state['bbox'][3],650)
    def test_anchor_tracks_actual_changed_map_extent(self):
        folder=ROOT/'data/v2/v2_trial_5aa90fc7327340cf';parser=PauseMap()
        seed=parser.parse(cv2.imread(str(folder/'0000-initial.jpg')));anchor=SpawnMapAnchor.from_map(seed)
        before=parser.parse(cv2.imread(str(folder/'0415-planning-map.jpg')));after=parser.parse(cv2.imread(str(folder/'0424-navigation-result-map.jpg')))
        evidence=anchor.motion(before,after,'left')
        self.assertTrue(evidence['verified']);self.assertGreater(evidence['direction_progress'],20)
        self.assertLess(abs(evidence['dy']),3)
    def test_portrait_counter_is_not_enemy(self):
        frame=cv2.imread(str(ROOT/'data/v2/v2_trial_dfcf9912d4a94e9e/0006-before-move.jpg'))
        self.assertEqual(SpatialVision().entities(frame)['enemy_count'],0)
    def test_real_enemy_bar_remains_detected(self):
        frame=cv2.imread(str(ROOT/'data/v2/v2_calibration_d2d8d6f70ec4472f/0004-after-move.jpg'))
        self.assertGreater(SpatialVision().entities(frame)['enemy_count'],0)
    def test_spawn_marker_sliver_is_not_exploration_destination(self):
        frame=cv2.imread(str(ROOT/'data/v2/recovery-spawn-paused.png'));parser=PauseMap();state=parser.parse(frame)
        plan=parser.exploration_plan(state)
        self.assertGreater(len(plan['path']),2);self.assertEqual(plan['direction'],'up');self.assertLess(plan['target'][0],800)
    def test_pause_pin_does_not_disconnect_corridor(self):
        path=ROOT/'data/v2/v2_calibration_f2a3ea3b17574c90/0019-planning-map.jpg'
        state=PauseMap().parse(cv2.imread(str(path)));plan=PauseMap().next_motion(state,[590,300]);self.assertEqual(plan['direction'],'left')
    def test_real_large_camera_motion(self):
        folder=ROOT/'data/v2/v2_calibration_7594db2bc4b1496a'
        before=cv2.imread(str(folder/'0003-before-move.jpg'));after=cv2.imread(str(folder/'0004-after-move.jpg'))
        self.assertIsNotNone(before);result=SpatialVision.motion(before,after,[800,445],[800,445])
        self.assertTrue(result['moved']);self.assertLess(result['effective_dy'],-100)
    def test_historical_chat_and_boots(self):
        vision=InteractionVision(ROOT)
        self.assertTrue(vision.affordance(cv2.imread(str(ROOT/'captures/1794088601124454200-before.png'))))
        self.assertFalse(vision.affordance(cv2.imread(str(ROOT/'data/v2/v2_calibration_45124c972be4410b/0048-after-jogo.jpg'))))

class SimulatedStageIntegration(unittest.TestCase):
    setUp=V2Scenarios.setUp
    tearDown=V2Scenarios.tearDown
    def trial(self,second_result,navigation_first=False):
        image=cv2.imread(str(ROOT/'data/v2/v2_calibration_45124c972be4410b/0054-after-pausa.jpg'))
        bot=SimpleNamespace(cancel=threading.Event(),adb=None,snapshot={},observe=lambda:None)
        sequence=['pausa','resultado',second_result];scope='world:1:passage:1'
        class Environment:
            def observe(self):
                scene=sequence.pop(0);bot.snapshot={'scene':scene,'words':[{'text':'Stage Clear'}] if scene=='resultado' else []}
                return Observation(uid('fixture'),now(),scene,.95,scope,scope,'',{'stage_confidence':.95,'stage_observed':True},provenance=Provenance('simulation'))
        runtime=CognitiveRuntime(Environment(),self.memory)
        path=self.path
        class Session:
            observation=FastSession.observation
            def __init__(self,*args):
                self.memory=runtime.memory;self.scope=scope;self.run_id=uid('simulated');self.folder=path/self.run_id;self.folder.mkdir();self.last_frame=image;self.world_features=None
                self.last_features={'scene':'pausa','at':now(),'frame':'fixture.png'}
                self.cycles=0
            def capture(self,label):return self.last_frame,self.last_features
            def check_cancel(self):pass
            def navigate_once(self):
                self.cycles+=1
                if navigation_first and self.cycles==1:return {'kind':'navigation','metrics':{'verified':True}}
                raise RuntimeError('Synthetic terminal transition')
            def close(self):return {'run_id':self.run_id,'actions':[],'seconds':0}
        (path/'evaluations/v2').mkdir(parents=True)
        with patch('cognitive.stage_v2.FastSession',Session):report=StageRunner(bot,runtime,path).run(2 if navigation_first else 1,10)
        return report,runtime
    def test_confirmed_result_persists_goal(self):
        report,runtime=self.trial('resultado');self.assertEqual(report['outcome'],'stage_complete')
        self.assertFalse(report['initial_spawn_verified']);self.assertEqual(self.memory.goals()[0]['state'],State.COMPLETED)
    def test_navigation_result_is_logged_and_next_cycle_runs(self):
        report,runtime=self.trial('resultado',navigation_first=True)
        self.assertEqual(report['outcome'],'stage_complete');self.assertEqual(report['metrics']['cycles'],2)
    def test_transient_result_does_not_complete_goal(self):
        report,runtime=self.trial('pausa');self.assertEqual(report['outcome'],'blocked')
        self.assertNotEqual(self.memory.goals()[0]['state'],State.COMPLETED)
    def test_initial_device_failure_blocks_without_input(self):
        class Environment:
            def observe(self):raise RuntimeError('fixture: device offline')
        runtime=CognitiveRuntime(Environment(),self.memory);bot=SimpleNamespace(cancel=threading.Event())
        with self.assertRaisesRegex(RuntimeError,'device offline'):StageRunner(bot,runtime,self.path).run(1,10)
        self.assertEqual(self.memory.goals()[0]['state'],State.BLOCKED)

class SimulatedMapAlignment(unittest.TestCase):
    def setUp(self):
        self.state=PauseMap().parse(cv2.imread(str(ROOT/'data/v2/v2_trial_5aa90fc7327340cf/0000-initial.jpg')))
        self.anchor=SpawnMapAnchor.from_map(self.state)
    def transformed(self,movement):
        scale=.85;dx,dy=120,40
        floor=cv2.warpAffine(self.state['floor'],np.float32([[scale,0,dx],[0,scale,dy]]),(1600,900),flags=cv2.INTER_NEAREST)
        # Additional revealed floor is away from the observed spawn anchor.
        cv2.rectangle(floor,(400,250),(550,330),255,-1)
        points=cv2.findNonZero(floor);bbox=list(cv2.boundingRect(points))
        px,py=self.state['player']
        return {'floor':floor,'bbox':bbox,'player':[(px+movement[0])*scale+dx,(py+movement[1])*scale+dy]}
    def test_zoom_and_translation_without_movement_is_not_progress(self):
        result=self.anchor.motion(self.state,self.transformed((0,0)),'left')
        self.assertIsNotNone(result.get('after_alignment'));self.assertFalse(result['verified'])
        self.assertLess(abs(result['dx']),3.5);self.assertLess(abs(result['dy']),3.5)
    def test_progress_survives_zoom_and_translation(self):
        result=self.anchor.motion(self.state,self.transformed((-20,0)),'left')
        self.assertTrue(result['verified']);self.assertAlmostEqual(result['direction_progress'],20,delta=3.5)
    def test_missing_anchor_does_not_invent_position(self):
        empty={'floor':np.zeros((900,1600),np.uint8),'bbox':[400,200,800,500],'player':[600,400]}
        result=self.anchor.motion(self.state,empty,'left');self.assertFalse(result['verified'])
    def test_wall_margin_scales_with_observed_map_zoom(self):
        state=self.transformed((0,0));state['map_scale']=.85
        target=[700*.85+120,300*.85+40]
        path=PauseMap().path(state,target)
        self.assertGreater(len(path),2)

class CombatTemporalGuards(unittest.TestCase):
    setUp=V2Scenarios.setUp
    tearDown=V2Scenarios.tearDown
    def combat_gap(self,missing_count):
        enemy={'kind':'enemy','bbox':[760,340,60,90]}
        frames=[{'scene':'jogo','health':1.,'player':None,'entities':[enemy],'frame':'synthetic-effect-'+str(i)} for i in range(missing_count)]
        frames+=[{'scene':'jogo','health':1.,'player':[800,445],'entities':[enemy],'frame':'synthetic-player-visible'}]
        frames+=[{'scene':'jogo','health':1.,'player':[800,445],'entities':[],'frame':'synthetic-clear'}]*3
        class Session:
            scope='world:1:passage:1';actions=[];current=None
            def check_cancel(self):pass
            def capture(self,label):self.current=frames.pop(0);return None,self.current
            def pulse(self,action,**kwargs):
                if self.current['player'] is None:raise AssertionError('Input while player was unlocated')
                self.actions.append(action)
        session=Session();session.memory=self.memory;return session
    def test_transient_effect_recovers_before_combat_input(self):
        session=self.combat_gap(2);result=FastSession.fight(session,seconds=2)
        self.assertEqual(result['perception_missing_observations'],2);self.assertEqual(result['perception_recoveries'],1)
        self.assertEqual(len(session.actions),1)
    def test_persistent_player_loss_stops_without_attack(self):
        session=self.combat_gap(4)
        with self.assertRaisesRegex(RuntimeError,'four bounded'):FastSession.fight(session,seconds=2)
        self.assertEqual(session.actions,[])
    def test_dark_depleted_bar_is_not_full_health(self):
        frame=np.full((900,1600,3),(80,110,150),np.uint8)
        cv2.rectangle(frame,(349,90),(423,102),(40,85,40),-1)
        cv2.rectangle(frame,(349,90),(378,102),(60,235,60),-1)
        self.assertAlmostEqual(SpatialVision().entities(frame)['health'],.4,delta=.04)
    def test_enemy_lost_during_capture_withholds_input(self):
        session=FastSession.__new__(FastSession);session.memory=self.memory;session.scope='world:1:passage:1'
        session.check_cancel=lambda:None
        session.capture=lambda label:(None,{'scene':'jogo','enemy_count':0,'frame':'synthetic-no-enemy.png'})
        session.adb=SimpleNamespace(foreground=lambda:True)
        result=session.pulse(Action('attack',{'ms':850}),require_enemy=True)
        self.assertTrue(result['withheld']);self.assertEqual(self.memory.retrieve(session.scope,kind='v2_action_withheld')[0]['content']['reason'],'enemy_lost_before_input')
    def test_melee_enemy_bar_is_not_filtered_as_player(self):
        frame=np.full((900,1600,3),(80,110,150),np.uint8)
        cv2.rectangle(frame,(350,90),(420,101),(0,210,0),-1)
        cv2.rectangle(frame,(770,350),(829,404),(220,220,220),-1)
        cv2.rectangle(frame,(760,440),(850,462),(20,20,20),-1)
        cv2.rectangle(frame,(765,445),(844,455),(0,0,220),-1)
        result=SpatialVision().entities(frame);self.assertEqual(result['enemy_count'],1)

if __name__=='__main__':
    from evaluations.v2.test_puzzle import PuzzleScenarios
    from evaluations.v2.test_navigation_recovery import RecoveryScenarios,LanternHistoricalVision
    from evaluations.v2.test_lantern import LanternGuards
    from evaluations.v2.test_hazards import HazardEndpoints
    groups={};success=True
    for cls,kind in ((V2Scenarios,'simulated'),(SimulatedStageIntegration,'simulated_stage_integration'),(PuzzleScenarios,'simulated_puzzle_controller'),(SimulatedMapAlignment,'simulated_map_alignment'),(CombatTemporalGuards,'simulated_combat_guard'),(RecoveryScenarios,'simulated_recovery_and_initial_state'),(LanternGuards,'simulated_lantern_guards'),(HazardEndpoints,'simulated_hazard_endpoints'),(HistoricalCaptures,'historical_real_screenshots'),(LanternHistoricalVision,'historical_lantern_vision')):
        start=time.perf_counter();suite=unittest.defaultTestLoader.loadTestsFromTestCase(cls)
        with (ROOT/f'logs/v2-tests-{kind}.txt').open('w',encoding='utf-8') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
        groups[kind]={'tests':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors),'failures':[(str(t),message) for t,message in result.failures+result.errors],'duration_ms':round((time.perf_counter()-start)*1000,2)}
        success=success and result.wasSuccessful()
    report={'groups':groups,'real_stage_completion_proven':False,'scope':'Fixtures test controller decisions, persistence and visual recognition. Historical frames do not prove new actions were executed.'}
    (ROOT/'evaluations/v2/scenarios.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if success else 1)
