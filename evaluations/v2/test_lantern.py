from pathlib import Path
from types import SimpleNamespace
import unittest,time
from unittest.mock import Mock
import cv2
from cognitive.lantern_control import LanternController
from cognitive.fast_control import FastSession
from cognitive.spatial import SpatialVision
from cognitive.lantern_vision import LanternVision
import tempfile,struct,numpy as np
ROOT=Path(__file__).resolve().parents[2]

class LanternGuards(unittest.TestCase):
    def test_neutral_boots_withholds_pickup_even_near_object(self):
        frame=cv2.imread(str(ROOT/'data/v2/v2_calibration_45124c972be4410b/0048-after-jogo.jpg'))
        session=SimpleNamespace(scope='world:1:passage:1',root=ROOT,pulse=Mock(),check_cancel=lambda:None)
        controller=LanternController(session);controller.event=lambda *a,**k:None
        # Simulated proximity must not turn a neutral control into an affordance.
        controller.approach=lambda kind:(frame,{'player':[800,445],'frame':'simulation:neutral'}, {'bbox':[780,390,60,60]})
        with self.assertRaisesRegex(RuntimeError,'affordance not established'):controller.pickup()
        session.pulse.assert_not_called()
    def test_expired_budget_sends_no_game_input(self):
        session=SimpleNamespace(scope='world:1:passage:1',pulse=Mock(),check_cancel=lambda:None)
        controller=LanternController(session);controller.deadline=time.monotonic()-1
        with self.assertRaisesRegex(RuntimeError,'time budget'):controller.observe('expired')
        session.pulse.assert_not_called()
    def test_visible_enemy_interrupts_before_puzzle_input(self):
        session=SimpleNamespace(scope='world:1:passage:1',pulse=Mock(),check_cancel=lambda:None,capture=lambda label:(None,{'scene':'jogo','player':[800,445],'enemy_count':1}))
        controller=LanternController(session)
        with self.assertRaisesRegex(RuntimeError,'Combat interrupts'):controller.observe('enemy')
        session.pulse.assert_not_called()
    def test_unsupported_scope_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'Unsupported lantern scope'):LanternController(SimpleNamespace(scope='world:2:stage:1'))
    def test_uniform_android_buffer_reobserves_without_input(self):
        image=cv2.imread(str(ROOT/'data/v2/v2_trial_99d348c7cb44486e/0315-before-move.jpg'))
        def raw(frame):return struct.pack('<4I',1600,900,1,0)+cv2.cvtColor(frame,cv2.COLOR_BGR2RGBA).tobytes()
        adb=SimpleNamespace(call=Mock(side_effect=[raw(np.full_like(image,32)),raw(image)]))
        with tempfile.TemporaryDirectory(dir=ROOT/'data/v2') as folder:
            session=FastSession.__new__(FastSession);session.memory=SimpleNamespace(acquire=lambda *a,**k:True,remember=Mock());session.owner='simulation';session.scope='world:1:passage:1';session.folder=Path(folder);session.root=ROOT;session.frames=0;session.adb=adb
            session.vision=SpatialVision();session.lantern_vision=LanternVision(ROOT);session.held_object_kind=None;session.frame_callback=None
            _,features=session.capture('simulation')
            self.assertEqual(features['scene'],'jogo');self.assertEqual(adb.call.call_count,2);session.memory.remember.assert_called_once()
