import unittest
import cv2
import numpy as np
from pathlib import Path
from cognitive.map_navigation import PauseMap
from cognitive.v3.segments import SegmentPlanner,clear_line

class SegmentTests(unittest.TestCase):
    def test_full_revealed_map_pin_occlusion_does_not_select_similar_exit_room(self):
        from cognitive.map_anchor import SpawnMapAnchor
        root=Path(__file__).resolve().parents[2]
        anchor=SpawnMapAnchor(cv2.imread(str(root/'data/v2/v2_trial_5aa90fc7327340cf/spawn-map-anchor-derived.png'),0),[838,449],[918,647])
        state=PauseMap().parse(cv2.imread(str(root/'data/v2/v2_preparation_be1d7e9704fd4785/007-pausa.jpg')))
        alignment=anchor.locate(state);self.assertIsNotNone(alignment);self.assertGreater(alignment['score'],.98);self.assertTrue(anchor.is_spawn(state));self.assertGreater(alignment['top_left'][0],900)
        original=state['floor'].copy();self.assertTrue(anchor.restore_marker_floor(state,alignment));changed=np.argwhere(original!=state['floor']);x,y,w,h=state['player_marker_bbox'];self.assertTrue(all(x<=cx<x+w and y<=cy<y+h for cy,cx in changed))
        state['map_scale']=alignment['scale'];target=[(918-838)*alignment['scale']+alignment['top_left'][0],(577-449)*alignment['scale']+alignment['top_left'][1]]
        plan=SegmentPlanner(.06).plan(state,target);self.assertEqual(len(plan['segments']),1)
    def test_revealed_map_keeps_the_actual_pin_above_old_200_pixel_crop(self):
        root=Path(__file__).resolve().parents[2];frame=cv2.imread(str(root/'data/v3/v3_trial_7be9bd0f5cb64779/0304-v3-segment-after-map.jpg'))
        state=PauseMap().parse(frame);self.assertLess(state['player'][1],220);self.assertGreater(state['player'][1],170)
    def test_complete_reference_restores_only_observed_pin_at_room_corner(self):
        import json
        from cognitive.map_anchor import SpawnMapAnchor
        from cognitive.v3.session import GameplaySession
        root=Path(__file__).resolve().parents[2];metadata=json.loads((root/'assets/v3/passage1_full_map_reference.json').read_text())
        anchor=SpawnMapAnchor.load({'scope':'world:1:passage:1','path':str(root/'data/v2/v2_trial_5aa90fc7327340cf/spawn-map-anchor-derived.png'),'origin':[838,449],'spawn_point':[918,647],'identity':metadata['anchor_identity']},root)
        state=PauseMap().parse(cv2.imread(str(root/'data/v3/v3_trial_b09c6691d29a412e/0380-v3-room-before-map.jpg')));before=state['floor'].copy();alignment=anchor.locate(state);anchor.restore_marker_floor(state,alignment);state['map_scale']=alignment['scale']
        x,y,w,h=state['player_marker_bbox'];changed=np.argwhere(before!=state['floor']);self.assertGreater(len(changed),100);self.assertTrue(all(x<=cx<x+w and y<=cy<y+h for cy,cx in changed));self.assertLessEqual(len(SegmentPlanner(.06).plan(state,GameplaySession.raw_target([426,713],alignment))['segments']),3)

    def test_shallow_route_keeps_both_axes_using_supported_eight_direction_holds(self):
        floor=np.zeros((900,1600),np.uint8);floor[200:700,500:1100]=255
        plan=SegmentPlanner(.06).plan({'floor':floor,'player':[800,640],'map_scale':1.},[760,250])
        self.assertGreater(len(plan['segments']),1)
        for row in plan['segments']:
            x,y=map(abs,row['direction']);self.assertTrue(x<1e-6 or y<1e-6 or abs(x-y)<1e-6)
        self.assertLess(np.linalg.norm(np.array(plan['segments'][-1]['end'])-[760,250]),4)

    def test_optional_live_object_approach_never_targets_a_disconnected_floor_island(self):
        from cognitive.map_navigation import PauseMap
        floor=np.zeros((100,100),np.uint8);floor[20:80,10:40]=255;floor[20:80,70:95]=255
        state={'floor':floor,'player':[20,50]};parser=PauseMap()
        with self.assertRaises(ValueError):parser.path(state,[80,50],cell=4,margin=2)
        route=parser.path(state,[80,50],cell=4,margin=2,reachable_target=True)
        self.assertTrue(all(point[0]<40 for point in route))
    def test_long_clear_corridor_becomes_one_continuous_segment(self):
        floor=np.zeros((900,1600),np.uint8);floor[200:700,500:1100]=255
        state={'floor':floor,'player':[800,650],'map_scale':1.}
        plan=SegmentPlanner(.06).plan(state,[800,250]);self.assertEqual(len(plan['segments']),1);self.assertGreater(plan['segments'][0]['duration_ms'],6000)
    def test_wall_corner_is_kept_as_a_checkpoint(self):
        floor=np.zeros((900,1600),np.uint8);floor[200:700,500:620]=255;floor[200:320,500:1100]=255
        state={'floor':floor,'player':[560,640],'map_scale':1.};plan=SegmentPlanner(.06).plan(state,[1040,260]);self.assertGreater(len(plan['segments']),1)
        clearance=cv2.distanceTransform(floor,cv2.DIST_L2,5)
        self.assertTrue(all(clear_line(clearance,s['start'],s['end'],12) for s in plan['segments']))
    def test_unknown_floor_is_not_crossed_to_shorten_route(self):
        floor=np.zeros((900,1600),np.uint8);floor[300:500,400:700]=255;floor[300:500,900:1200]=255
        with self.assertRaises(ValueError):SegmentPlanner(.06).plan({'floor':floor,'player':[500,400]},[1000,400])
    def test_input_duration_requires_measured_positive_speed(self):
        with self.assertRaises(ValueError):SegmentPlanner(0)
    def test_real_spawn_marker_handles_half_pixel_map_rounding(self):
        root=Path(__file__).resolve().parents[2];frame=cv2.imread(str(root/'data/v2/v2_preparation_4f9c8cf96cb1455c/017-pausa.jpg'))
        state=PauseMap().parse(frame);state['map_scale']=.94;target=[state['player'][0],state['player'][1]-80*.94]
        plan=SegmentPlanner(.059537).plan(state,target);self.assertTrue(plan['segments']);self.assertFalse(plan['unobserved_space_crossed'])
    def test_new_spawn_can_escape_into_clearance_without_tiny_extra_action(self):
        root=Path(__file__).resolve().parents[2];frame=cv2.imread(str(root/'data/v3/v3_prefix_probe_efe3c3e40c684492/0003-v3-segment-before-map.jpg'))
        state=PauseMap().parse(frame);state['map_scale']=.94;target=[state['player'][0],state['player'][1]-70*.94]
        plan=SegmentPlanner(.059537).plan(state,target);self.assertEqual(len(plan['segments']),1);self.assertGreater(plan['segments'][0]['duration_ms'],1000)
    def test_start_escape_does_not_allow_following_or_crossing_wall(self):
        floor=np.zeros((900,1600),np.uint8);floor[200:700,500:1100]=255;distance=cv2.distanceTransform(floor,cv2.DIST_L2,5)
        self.assertTrue(clear_line(distance,[510,640],[650,640],12,start_escape=True))
        self.assertFalse(clear_line(distance,[510,640],[510,400],12,start_escape=True))
        self.assertFalse(clear_line(distance,[510,640],[490,640],12,start_escape=True))
    def test_real_npc_bypass_uses_clear_cell_centers(self):
        root=Path(__file__).resolve().parents[2];frame=cv2.imread(str(root/'data/v3/v3_prefix_probe_0cfcc153895d4ae2/0010-v3-segment-before-map.jpg'))
        state=PauseMap().parse(frame);state['map_scale']=.94;plan=SegmentPlanner(.059537).plan(state,[938,569]);self.assertTrue(plan['segments'])
        distance=cv2.distanceTransform(state['floor'],cv2.DIST_L2,5)
        self.assertTrue(all(clear_line(distance,s['start'],s['end'],12*.94,start_escape=i==0) for i,s in enumerate(plan['segments'])))

if __name__=='__main__':unittest.main()
