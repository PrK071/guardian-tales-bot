from pathlib import Path
import tempfile,time,unittest
from types import SimpleNamespace
import cv2
from cognitive.contracts import Provenance
from cognitive.memory import Memory
from cognitive.map_navigation import PauseMap
from cognitive.map_anchor import SpawnMapAnchor
from cognitive.fast_control import FastSession
from cognitive.stage_v2 import StageRunner
from cognitive.lantern_vision import LanternVision
ROOT=Path(__file__).resolve().parents[2];SCOPE='world:1:passage:1'

class RecoveryScenarios(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'data/v2');self.folder=Path(self.tmp.name);self.memory=Memory(self.folder/'memory.sqlite')
        self.spawn_frame=ROOT/'data/v2/v2_trial_5aa90fc7327340cf/0000-initial.jpg'
        self.spawn=PauseMap().parse(cv2.imread(str(self.spawn_frame)));self.anchor=SpawnMapAnchor.from_map(self.spawn)
        self.data=self.anchor.save(self.folder/'anchor.png')
        self.memory.remember('semantic','v2_spawn_anchor',SCOPE,self.data,Provenance('simulation:anchor'),.95,'verified')
    def tearDown(self):
        self.memory.close();assert self.folder.resolve().is_relative_to((ROOT/'data/v2').resolve());self.tmp.cleanup()
    def ticket(self):
        self.memory.remember('working','v2_prepared_spawn',SCOPE,{'prepared_at':time.time(),'frame':str(self.spawn_frame),'stage':SCOPE,'character_movements':0},Provenance('simulation:entry'),.98,'verified',dedupe='v2:prepared-spawn:'+SCOPE)
    def configured(self,state):
        runner=StageRunner(SimpleNamespace(),SimpleNamespace(memory=self.memory),ROOT)
        path=self.folder/('session-'+str(len(list(self.folder.iterdir()))));path.mkdir()
        session=SimpleNamespace(folder=path,run_id=path.name,reconsider_frontiers=lambda reason:None)
        return runner.configure_map_reference(session,state,SCOPE)
    def test_birth_requires_fresh_entry_evidence(self):
        self.assertFalse(self.configured(self.spawn));self.ticket();self.assertTrue(self.configured(self.spawn));self.assertFalse(self.configured(self.spawn))
    def test_another_bottom_room_is_not_birth(self):
        self.ticket();state=PauseMap().parse(cv2.imread(str(ROOT/'data/v2/v2_trial_99d348c7cb44486e/0320-planning-map.jpg')))
        state['player']=[634.5,675.]  # Synthetic marker at another bottom dead end.
        self.assertFalse(self.configured(state))
    def session_at_gate(self):
        state=PauseMap().parse(cv2.imread(str(ROOT/'data/v2/v2_trial_99d348c7cb44486e/0320-planning-map.jpg')))
        state['anchor_alignment']=self.anchor.locate(state);state['map_scale']=state['anchor_alignment']['scale']
        session=FastSession.__new__(FastSession);session.memory=self.memory;session.scope=SCOPE;session.run_id='synthetic-gate';session.map_anchor=self.anchor;session.deferred_frontiers=[]
        session.last_plan_state=state;session.last_plan=PauseMap().exploration_plan(state);session.last_features={'frame':'synthetic-stall-evidence'}
        session.failed_count=2;session.failed_edge=None;session.recovery_count=3
        return session,state
    def test_stalled_frontier_selects_a_different_observed_target(self):
        session,state=self.session_at_gate();original=session.last_plan['target'];result=session.defer_current_frontier('Observed edge blocked; bounded side-step recovery unavailable')
        self.assertIsNotNone(result['next_target']);self.assertNotEqual(result['next_target'],original);self.assertTrue(session.frontier_deferred(original,state))
        self.assertEqual(len(self.memory.retrieve(SCOPE,kind='v2_frontier_blocked')),1)
    def test_new_combat_allows_retest_without_claiming_gate_open(self):
        session,state=self.session_at_gate();point=session.last_plan['target'];session.defer_current_frontier('Observed edge blocked')
        session.reconsider_frontiers('new_visible_combat');self.assertFalse(session.frontier_deferred(point,state))
        saved=self.memory.retrieve(SCOPE,kind='v2_frontier_blocked')[0]['content'];self.assertLessEqual(saved['expires_at'],time.time());self.assertIn('retest_allowed',saved['state'])

class LanternHistoricalVision(unittest.TestCase):
    def test_portable_brazier_appearance_is_observed(self):
        frame=cv2.imread(str(ROOT/'data/v2/v2_trial_99d348c7cb44486e/0225-before-move.jpg'))
        objects=LanternVision(ROOT).detect(frame,[800,445]);self.assertTrue(any(o['kind']=='portable_brazier' for o in objects))
    def test_pickup_proximity_does_not_discard_the_ground_brazier(self):
        frame=cv2.imread(str(ROOT/'data/v2/v2_trial_99d348c7cb44486e/0225-before-move.jpg'))
        objects=LanternVision(ROOT).detect(frame,[928,260]);self.assertTrue(any(o['kind']=='portable_brazier' for o in objects))
    def test_orange_barrier_is_not_a_lit_lantern(self):
        frame=cv2.imread(str(ROOT/'data/v2/v2_trial_99d348c7cb44486e/0315-before-move.jpg'))
        objects=LanternVision(ROOT).detect(frame,[800,445]);self.assertFalse(any(o['kind']=='standing_lantern_lit' for o in objects));self.assertTrue(any(o['kind']=='standing_lantern_unlit' for o in objects))
