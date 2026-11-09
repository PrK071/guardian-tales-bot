from pathlib import Path
import unittest,cv2
from cognitive.spatial import SpatialVision
ROOT=Path(__file__).resolve().parents[2]

class HistoricalEnemies(unittest.TestCase):
    def test_follower_hair_is_not_an_enemy_bar(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_e612ff90dc6c49a5/0013-v3-fixed-contact-progress.jpg'))
        self.assertFalse(SpatialVision().entities(frame)['combat_present'])

    def test_real_flashing_slime_bar_does_not_signal_combat_end(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_trial_fc9987b7a2f24df6/0079-v3-live-observation.jpg'))
        result=SpatialVision().entities(frame);self.assertTrue(result['combat_present']);self.assertGreater(result['focused_enemy_hp']['red_area'],1000)
    def test_real_highlighted_fill_with_dark_border_is_still_an_enemy(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_trial_3b7a6bd370d14fbd/0004-v3-objective-check.jpg'))
        result=SpatialVision().entities(frame);self.assertGreaterEqual(result['enemy_count'],1)
    def test_top_cave_pixels_do_not_interrupt_a_clear_corridor(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_combat_setup_f8d06c2cd6c34fdf/0023-v3-live-observation.jpg'))
        self.assertFalse(SpatialVision().entities(frame)['combat_present'])
    def test_clipped_and_nearly_empty_real_enemy_bars_are_not_all_lost(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_prefix_probe_55a02c03b57c4499/0037-encounter-trigger-observe.jpg'))
        result=SpatialVision().entities(frame);self.assertGreaterEqual(result['enemy_count'],1)
    def test_real_npc_and_portraits_are_not_enemy_bars(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_input_probe_175b38f9a0cc40f3/0003-before-continuous-input.jpg'))
        self.assertEqual(SpatialVision().entities(frame)['enemy_count'],0)

if __name__=='__main__':unittest.main()
