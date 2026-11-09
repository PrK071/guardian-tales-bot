import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from cognitive.hazard_control import crossing_endpoint
from cognitive.fast_control import FastSession
from cognitive.contracts import Action

class HazardEndpoints(unittest.TestCase):
    def test_overlap_escapes_column_instead_of_vertical_oscillation(self):
        state={'player':[794,445],'entities':[{'kind':'hazard','bbox':[713,400,114,140]}]}
        result=crossing_endpoint(state,'left',1500)
        self.assertIsNotNone(result);self.assertGreater(result['ms'],300);self.assertLess(result['ms'],500)
        self.assertFalse(result['collision_free_claim'])
    def test_crossing_stops_between_two_observed_columns(self):
        state={'player':[794,445],'entities':[{'kind':'hazard','bbox':[376,200,114,140]},{'kind':'hazard','bbox':[39,500,114,140]}]}
        result=crossing_endpoint(state,'left',1500);end=794-result['ms']*.44
        self.assertGreater(abs(end-433),140);self.assertGreater(abs(end-96),140)
    def test_endpoint_does_not_overrun_observed_straight_floor(self):
        state={'player':[794,445],'entities':[{'kind':'hazard','bbox':[376,200,114,140]}]}
        self.assertIsNone(crossing_endpoint(state,'left',300))
    def test_actor_absence_has_no_crossing_proposal(self):
        self.assertIsNone(crossing_endpoint({'player':None},'left',1500))
    def test_fresh_low_health_withholds_previously_planned_move(self):
        session=FastSession.__new__(FastSession);session.check_cancel=lambda:None;session.adb=SimpleNamespace(foreground=lambda:True,hold=Mock(),move=Mock())
        session.capture=lambda label:(None,{'scene':'jogo','health':.24,'player':[800,445]})
        with self.assertRaisesRegex(RuntimeError,'pre-input observation'):session.pulse(Action('move',{'direction':'left','ms':900}))
        session.adb.hold.assert_not_called();session.adb.move.assert_not_called()
    def test_fresh_missing_actor_withholds_planned_move(self):
        session=FastSession.__new__(FastSession);session.check_cancel=lambda:None;session.adb=SimpleNamespace(foreground=lambda:True,hold=Mock(),move=Mock())
        session.capture=lambda label:(None,{'scene':'jogo','health':1.,'player':None})
        with self.assertRaisesRegex(RuntimeError,'character absent'):session.pulse(Action('move',{'direction':'left','ms':900}))
        session.adb.hold.assert_not_called();session.adb.move.assert_not_called()
