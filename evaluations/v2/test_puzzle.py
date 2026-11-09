"""Synthetic puzzle-controller evidence. No Android commands or game success."""
from pathlib import Path
import tempfile,threading,unittest
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import numpy as np
from cognitive.memory import Memory
from cognitive.puzzle_control import BombRockController,pickup_evidence,removal_evidence

ROOT=Path(__file__).resolve().parents[2]
ALIGNMENT={'confidence':1.,'background_dx':0.,'background_dy':0.}
STEPS=['approach_observed_bomb','interact_and_verify_pickup','face_observed_rock','interact_and_verify_obstacle_change']

def image(held=False,removed=False,retain_plant=False):
    frame=np.full((900,1600,3),(80,110,150),np.uint8)
    cv2.rectangle(frame,(1400,700),(1465,760),(255,255,255),-1)
    if not removed:cv2.rectangle(frame,(550,360),(649,539),(150,220,150),-1)
    if not held or retain_plant:cv2.rectangle(frame,(735,375),(764,404),(220,220,0),-1)
    if held:cv2.rectangle(frame,(785,280),(814,309),(220,220,0),-1)
    return frame

class PuzzleScenarios(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'data/v2');self.path=Path(self.tmp.name);self.memory=Memory(self.path/'memory.sqlite')
    def tearDown(self):
        self.memory.close();assert self.path.resolve().is_relative_to((ROOT/'data/v2').resolve());self.tmp.cleanup()
    def test_disappearance_without_held_object_is_not_pickup(self):
        before=image();after=image();cv2.rectangle(after,(735,375),(764,404),(80,110,150),-1)
        evidence=pickup_evidence(before,after,[720,350,80,90],[800,445],[800,445],ALIGNMENT)
        self.assertFalse(evidence['verified'])
    def test_observed_core_transfer(self):
        evidence=pickup_evidence(image(),image(held=True),[720,350,80,90],[800,445],[800,445],ALIGNMENT)
        self.assertTrue(evidence['verified'])
    def test_explosion_flash_is_not_removed_rock(self):
        before=image();after=before.copy();after[360:540,550:650]=255
        self.assertFalse(removal_evidence(before,after,[550,360,100,180],ALIGNMENT)['verified'])
    def test_offscreen_rock_is_not_removed_rock(self):
        evidence=removal_evidence(image(),image(removed=True),[550,360,100,180],{**ALIGNMENT,'background_dx':1200})
        self.assertFalse(evidence['verified']);self.assertEqual(evidence['reason'],'target_left_visible_frame')
    def test_alignment_uncertainty_blocks_success(self):
        self.assertFalse(removal_evidence(image(),image(removed=True),[550,360,100,180],{**ALIGNMENT,'confidence':.1})['verified'])
    def session(self,bad_transfer=False):
        memory=self.memory
        class Session:
            root=ROOT;scope='world:1:passage:1';run_id='simulated_puzzle';interactions=0;cancel=threading.Event()
            def __init__(self):self.last_frame=image();self.last_features=self.features()
            def features(self):
                entities=[{'kind':'bomb_candidate','bbox':[720,350,80,90],'confidence':.7}]
                if self.interactions<2:entities.append({'kind':'rock_obstacle_candidate','bbox':[550,360,100,180],'confidence':.7})
                return {'scene':'jogo','player':[800,445],'health':1.,'enemy_count':0,'entities':entities}
            def check_cancel(self):pass
            def capture(self,label):return self.last_frame,self.last_features
            def pulse(self,action):
                action.validate()
                if action.op=='interact':self.interactions+=1
                self.last_frame=image(held=self.interactions==1,removed=self.interactions>=2,retain_plant=bad_transfer)
                self.last_features=self.features()
                return {'metrics':{'motion':ALIGNMENT}}
        session=Session();session.memory=memory;return session
    def test_controller_two_confirmations_do_not_clear_stage(self):
        session=self.session();controller=BombRockController(session,{'validation':'hypothesis','memory_id':'synthetic_source','steps':STEPS})
        with patch('cognitive.puzzle_control.SpatialVision.motion',return_value=ALIGNMENT):result=controller.solve()
        self.assertTrue(result['verified']);self.assertEqual(result['confirmations'],2);self.assertFalse(result['stage_complete']);self.assertEqual(session.interactions,2)
        self.assertEqual(self.memory.retrieve(session.scope,kind='v2_puzzle_solution')[0]['validation'],'verified')
    def test_failed_pickup_prevents_throw(self):
        session=self.session(bad_transfer=True);controller=BombRockController(session,{'validation':'hypothesis','memory_id':'synthetic_source','steps':STEPS})
        with patch('cognitive.puzzle_control.SpatialVision.motion',return_value=ALIGNMENT):
            with self.assertRaisesRegex(RuntimeError,'Pickup not verified'):controller.solve()
        self.assertEqual(session.interactions,1);self.assertEqual(self.memory.retrieve(session.scope,kind='v2_puzzle_solution'),[])
