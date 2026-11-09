from unittest.mock import patch
import unittest
import numpy as np
from cognitive.v3.exploration import visible_floor_horizon

class ExplorationTests(unittest.TestCase):
    def evaluate(self,floor,features=None):
        features=features or {'player':[800,450],'enemy_count':0,'entities':[]}
        with patch('cognitive.v3.exploration.SpatialVision.floor_mask',return_value=floor.copy()):return visible_floor_horizon(np.zeros((900,1600,3),np.uint8),features,'up')
    def test_visible_open_floor_gets_a_moderate_continuous_horizon(self):
        floor=np.zeros((900,1600),np.uint8);floor[150:700,700:900]=255
        result=self.evaluate(floor);self.assertGreater(result['duration_ms'],400);self.assertLessEqual(result['duration_ms'],600)
    def test_void_beyond_actor_is_not_extended(self):
        floor=np.zeros((900,1600),np.uint8);self.assertIsNone(self.evaluate(floor))
    def test_an_observed_rock_shortens_the_horizon_before_its_edge(self):
        floor=np.zeros((900,1600),np.uint8);floor[150:700,700:900]=255
        f={'player':[800,450],'enemy_count':0,'entities':[{'kind':'rock_obstacle_candidate','bbox':[740,280,120,80]}]}
        self.assertIsNone(self.evaluate(floor,f))
    def test_enemy_presence_withholds_exploration(self):
        floor=np.full((900,1600),255,np.uint8);self.assertIsNone(self.evaluate(floor,{'player':[800,450],'enemy_count':1,'entities':[]}))
