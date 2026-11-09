from pathlib import Path
from types import SimpleNamespace
import unittest,cv2
from cognitive.lantern_control import LanternController
from cognitive.lantern_vision import LanternVision
ROOT=Path(__file__).resolve().parents[2]

class LanternTrackingTests(unittest.TestCase):
    def test_actual_helmet_edge_keeps_actor_visible_during_follower_overlap(self):
        from cognitive.spatial import SpatialVision
        frame=cv2.imread(str(ROOT/'data/v3/v3_trial_6a36ce2f389148b1/0020-v3-room-visual-plan.jpg'));f=SpatialVision().entities(frame)
        self.assertIsNotNone(f['player']);self.assertAlmostEqual(f['player'][0],800.5,delta=3);self.assertAlmostEqual(f['player'][1],445,delta=3)
        frame=cv2.imread(str(ROOT/'data/v3/v3_trial_89ddabd263f144db/0020-v3-room-visual-plan.jpg'));f=SpatialVision().entities(frame);self.assertAlmostEqual(f['player'][1],445,delta=3)

    def test_lower_fixed_lantern_is_recognized_when_wall_occludes_pedestal_foot(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_215c1f24d894442e/0030-v3-fixed-independent-check.jpg'))
        objects=LanternVision(ROOT).detect(frame,[800.5,445],True);lit=[o for o in objects if o['kind']=='standing_lantern_lit'];self.assertEqual(len(lit),2);self.assertTrue(any(o['pedestal_bbox'][1]>700 for o in lit))

    def test_helmet_is_not_the_nearby_tool_bubble_or_joined_silver_rock(self):
        from cognitive.spatial import SpatialVision
        for name in ['0002-v3-glove-preflight.jpg','0005-v3-glove-removal-check.jpg']:
            frame=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_1c712db0ca8c40f8'/name));f=SpatialVision().entities(frame)
            self.assertAlmostEqual(f['player'][1],445,delta=3)

    def test_long_hold_camera_translation_exceeds_lk_range_without_losing_target(self):
        from cognitive.spatial import SpatialVision
        folder=ROOT/'data/v3/v3_lantern_probe_79336133987c4ba1'
        before=cv2.imread(str(folder/'0004-v3-before-move.jpg'));after=cv2.imread(str(folder/'0006-v3-fixed-contact-progress.jpg'))
        motion=SpatialVision.motion(before,after,[806,445],[806,445]);self.assertGreater(motion['confidence'],.6);self.assertAlmostEqual(motion['background_dx'],-172.8,delta=2);self.assertTrue(motion['moved'])

    def test_burning_side_rim_survives_strong_flame_and_source_illumination(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_6345272ccf18440b/0002-lantern-held-reconcile.jpg'))
        held=LanternVision(ROOT).held_match(frame,[800,445]);self.assertGreater(held['confidence'],.95);self.assertEqual(held['bbox'],[746,277,110,106])
    def test_narrow_pocket_escapes_around_visible_rock_before_crossing_room(self):
        from cognitive.puzzle_control import BombRockController
        from cognitive.spatial import SpatialVision
        frame=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_5a60e7eb73cd4ee3/0009-v3-room-visual-plan.jpg'))
        f={'player':[800,445],'actor_pose_source':'calibrated_carried_brazier_offset','entities':SpatialVision().entities(frame)['entities']}
        heading,ms=BombRockController.local_approach(frame,f,[1195,487]);self.assertEqual(heading,'left');self.assertLess(ms,150)
    def test_ground_brazier_is_not_the_carried_item_when_helmet_is_occluded(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_5ec86dcd614649b7/0002-lantern-held-reconcile.jpg'));vision=LanternVision(ROOT);offset=[-.027,1.547]
        ground=vision.held_match(frame,[1177,252]);carried=vision.held_match(frame,[800,445])
        self.assertFalse(vision.carried_actor_visible(frame,ground,offset));self.assertTrue(vision.carried_actor_visible(frame,carried,offset));self.assertEqual(carried['bbox'],[746,277,110,106])
    def test_ignited_carried_brazier_keeps_actor_tracking_through_animated_fire(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_bfb023d72c2b4baf/0021-lantern-approach-result.jpg'))
        held=LanternVision(ROOT).held_match(frame,[800,445]);self.assertGreater(held['confidence'],.8);self.assertEqual(held['bbox'],[746,277,110,106])
    def test_floor_fire_is_distinct_from_decorative_wall_sconces(self):
        vision=LanternVision(ROOT)
        floor=cv2.imread(str(ROOT/'data/v2/v2_trial_99d348c7cb44486e/0205-before-move.jpg'));wall=cv2.imread(str(ROOT/'data/v2/v2_trial_99d348c7cb44486e/0065-before-move.jpg'))
        self.assertTrue(any(o['kind']=='standing_lantern_lit' for o in vision.detect(floor)))
        self.assertFalse(any(o['kind']=='standing_lantern_lit' for o in vision.detect(wall)))
        close_wall=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_890aa5bcea844537/0058-after-jogo.jpg'))
        self.assertFalse(any(o['kind']=='standing_lantern_lit' for o in vision.detect(close_wall)))
    def test_real_nearby_brazier_remains_visible_when_pickup_bubble_appears(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_10454402c3324fbf/0020-lantern-approach-result.jpg'))
        objects=LanternVision(ROOT).detect(frame,[798,443]);brazier=[o for o in objects if o['kind']=='portable_brazier']
        self.assertEqual(len(brazier),1);self.assertGreater(brazier[0]['confidence'],.95)
    def test_observed_hand_and_throw_arrow_are_distinct_affordances(self):
        c=LanternController.__new__(LanternController);c.s=SimpleNamespace(root=ROOT)
        hand=cv2.imread(str(ROOT/'data/v3/v3_trial_042e8212b28a46f5/0369-v3-before-move.jpg'));arrow=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_a88dd291b03d404f/0005-lantern-pickup-result.jpg'))
        self.assertTrue(c.pickup_hand(hand));self.assertFalse(c.pickup_hand(arrow))
    def test_real_carried_brazier_survives_follower_background_occlusion(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_bd77687b90034846/0002-lantern-held-reconcile.jpg'))
        held=LanternVision(ROOT).held_match(frame,[800,445]);self.assertGreater(held['confidence'],.85);self.assertEqual(held['bbox'],[746,277,110,106])
    def test_known_held_offset_recovers_actual_foot_instead_of_brazier_rim(self):
        held={'bbox':[746,277,110,106]};dx,dy=[-.008909090909091075,1.585];x,y,w,h=held['bbox'];foot=[x+w/2+dx*w,y+dy*h]
        self.assertAlmostEqual(foot[0],800.02,places=2);self.assertAlmostEqual(foot[1],445.01,places=2)
