import unittest
from cognitive.v3.observation import ThreatGate
from cognitive.v3.session import GameplaySession
from cognitive.v3.hazards import solid_spike
from cognitive.spatial import SpatialVision
from pathlib import Path
import cv2

def snap(sequence,enemy=True,near=False):
    return {'sequence':sequence,'features':{'enemy_count':int(enemy),'combat_present':enemy,'player':[800,450],'entities':[{'kind':'enemy','bbox':[770,350 if near else 0,80,90]}] if enemy else []}}

class ThreatTests(unittest.TestCase):
    def test_tiny_far_red_fragment_does_not_become_a_confirmed_encounter(self):
        gate=ThreatGate();first=snap(1);first['features']['enemy_red_area']=49
        self.assertFalse(gate.update(first));first['sequence']=2;self.assertFalse(gate.update(first))
        near=snap(3,near=True);near['features']['enemy_red_area']=8;self.assertTrue(gate.update(near))
    def test_real_blue_damage_number_is_not_a_solid_spike(self):
        root=Path(__file__).resolve().parents[2];frame=cv2.imread(str(root/'data/v3/v3_matched_combat_34f0407710434052/0033-v3-live-observation.jpg'))
        hazards=[e for e in SpatialVision().entities(frame)['entities'] if e['kind']=='hazard']
        self.assertTrue(hazards);self.assertFalse(any(solid_spike(frame,e) for e in hazards))
    def test_real_corridor_spikes_keep_the_hazard_guard(self):
        root=Path(__file__).resolve().parents[2];frame=cv2.imread(str(root/'data/v2/v2_lantern_calibration_cface23508d84a6d/0102-after-move.jpg'))
        hazards=[e for e in SpatialVision().entities(frame)['entities'] if e['kind']=='hazard']
        self.assertEqual(sum(solid_spike(frame,e) for e in hazards),2)
    def preflight(self,initial,fresh):
        session=GameplaySession.__new__(GameplaySession);session.check_cancel=lambda:None;calls=[]
        def capture(label):calls.append(label);return None,{'scene':'jogo','health':1,**fresh}
        session.capture=capture;return session.preflight_enemy(initial),calls
    def test_initial_distant_false_detection_is_reobserved_without_input(self):
        result,calls=self.preflight(snap(0)['features'],snap(1,False)['features']);self.assertFalse(result);self.assertEqual(len(calls),1)
    def test_initial_nearby_enemy_is_not_delayed_by_a_capture(self):
        result,calls=self.preflight(snap(0,near=True)['features'],{});self.assertTrue(result);self.assertEqual(calls,[])
    def test_unidentified_reobservation_never_permits_movement(self):
        with self.assertRaisesRegex(RuntimeError,'lost the gameplay'):self.preflight(snap(0)['features'],{'scene':'unknown','player':None})
    def test_one_distant_transient_does_not_stop_a_long_corridor(self):
        gate=ThreatGate();self.assertFalse(gate.update(snap(1)));self.assertFalse(gate.update(snap(2,False)))
    def test_same_cached_frame_does_not_confirm_a_distant_threat(self):
        gate=ThreatGate();self.assertFalse(gate.update(snap(1)));self.assertFalse(gate.update(snap(1)));self.assertTrue(gate.update(snap(2)))
    def test_melee_threat_stops_immediately(self):self.assertTrue(ThreatGate().update(snap(1,near=True)))
    def test_focused_enemy_hp_is_immediate_combat_evidence(self):
        snapshot=snap(1);snapshot['features']['focused_enemy_hp']={'red_area':500};self.assertTrue(ThreatGate().update(snapshot))
