from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest,cv2,time
from cognitive.lantern_vision import LanternVision
from cognitive.lantern_control import LanternController
from cognitive.spatial import SpatialVision
from cognitive.v3.rock_glove import drill_visible
from cognitive.v3.lantern_gate import lowered_stone_evidence,SOURCE
from cognitive.v3.puzzle import LanternSegment
ROOT=Path(__file__).resolve().parents[2]

class LanternFlowTests(unittest.TestCase):
    def test_nearby_brazier_with_neutral_boot_is_not_returned_as_pickup_ready(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_trial_1503120023e54414/0093-lantern-find-object.jpg'));vision=LanternVision(ROOT);features=SpatialVision().entities(frame);features['frame']='synthetic:neutral-near-brazier';features['puzzle_objects']=vision.detect(frame,features['player'],False)
        def pulse(action):raise RuntimeError('synthetic control withheld after planning approach')
        c=LanternController(SimpleNamespace(root=ROOT,scope='world:1:passage:1',lantern_vision=vision,transition=lambda *a:None,check_cancel=lambda:None,pulse=pulse));c.observe=lambda label:(frame,features)
        self.assertFalse(c.pickup_hand(frame))
        with patch('cognitive.lantern_control.BombRockController.local_approach',return_value=('left',100)):
            with self.assertRaisesRegex(RuntimeError,'synthetic control withheld'):c.approach('portable_brazier')
    def test_normal_observed_helmet_restores_own_lane_in_the_narrow_rock_pocket(self):
        from cognitive.puzzle_control import BombRockController
        frame=cv2.imread(str(ROOT/'data/v3/v3_trial_af8edc8e54904f0c/0033-v3-after-move.jpg'));features=SpatialVision().entities(frame)
        heading,duration=BombRockController.local_approach(frame,features,[400,-50]);self.assertEqual(heading,'up');self.assertLessEqual(duration,300)
    def test_carried_fire_near_occluded_unlit_target_does_not_end_contact_early(self):
        from cognitive.v3.fixed_lanterns import light_nearest
        frame=cv2.imread(str(ROOT/'data/v3/v3_trial_13f26b7f67ff4c73/0059-v3-fixed-contact-progress.jpg'));vision=LanternVision(ROOT);observations=[];moves=[]
        obj={'kind':'standing_lantern_unlit','bbox':[807,169,67,91]}
        def observe(label):
            f={'player':[800,445],'frame':'synthetic:contact'+str(len(observations)),'puzzle_objects':[obj] if not observations else []};observations.append(f);return frame,f
        def pulse(action):moves.append(action);return {'metrics':{'continuous_control':{'requested_ms':100}}}
        session=SimpleNamespace(lantern_vision=vision,pulse=pulse)
        controller=SimpleNamespace(check=lambda:None,observe=observe,objects=LanternController.objects,foot=LanternController.foot)
        motion={'confidence':1,'background_dx':0,'background_dy':0,'effective_dx':0,'effective_dy':0}
        with patch('cognitive.v3.fixed_lanterns.BombRockController.local_approach',return_value=('up',100)),patch('cognitive.v3.fixed_lanterns.SpatialVision.motion',return_value=motion):
            with self.assertRaisesRegex(RuntimeError,'contact stalled twice'):light_nearest(session,controller)
        self.assertEqual(len(moves),2)
    def test_occluded_unlit_brazier_requires_fresh_matching_tracking_and_current_pickup_icons(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_trial_d6d0100a530c4109/0091-v3-live-observation.jpg'))
        c=LanternController(SimpleNamespace(root=ROOT,scope='world:1:passage:1',lantern_vision=LanternVision(ROOT)));features={'player':[800,445]}
        tracked={'bbox':[761,293,110,106],'motion_confidence':.9,'at':time.time(),'source_frame':'synthetic:tracked-prior'}
        self.assertIsNone(c.pickup_candidate(frame,features));self.assertIsNotNone(c.pickup_candidate(frame,features,tracked))
        self.assertIsNone(c.pickup_candidate(frame,features,{**tracked,'at':time.time()-5}))
        self.assertIsNone(c.pickup_candidate(frame,features,{**tracked,'bbox':[400,293,110,106]}))
        self.assertIsNone(c.pickup_candidate(frame,features,{**tracked,'motion_confidence':.1}))
    def test_current_pickup_bubble_identifies_the_offered_burning_object(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_da3eadf996804cb6/0025-v3-after-move.jpg'))
        session=SimpleNamespace(root=ROOT,scope='world:1:passage:1',lantern_vision=LanternVision(ROOT));c=LanternController(session)
        obj=c.pickup_candidate(frame,{'player':[800.5,445]});self.assertIsNotNone(obj);self.assertEqual(obj['bbox'],[670,299,110,106])
    def test_actual_glove_sequence_verifies_the_near_tile_not_the_far_rock_behind_actor(self):
        folder=ROOT/'data/v3/v3_lantern_probe_c7253326189c4557';before=cv2.imread(str(folder/'0002-v3-glove-preflight.jpg'));after=cv2.imread(str(folder/'0005-v3-glove-removal-check.jpg'));index=[0]
        def capture(label):
            frame=before if index[0]==0 else after;index[0]+=1;f=SpatialVision().entities(frame);f['frame']='fixture:'+label;return frame,f
        session=SimpleNamespace(root=ROOT,scope='world:1:passage:1',run_id='fixture',transition=lambda *a:None,capture=capture,check_cancel=lambda:None,preflight_enemy=lambda f:False,memory=SimpleNamespace(remember=lambda *a,**k:None),pulse=lambda a:{'metrics':{}})
        with patch('cognitive.v3.rock_glove.time.sleep',lambda *a:None):result=drill_visible(session)
        self.assertTrue(result['verified']);self.assertEqual(len(result['tiles']),1);row=result['tiles'][0];self.assertGreater(row['tile_bbox'][1],400);self.assertLess(row['rock_pixels_remaining']/row['rock_pixels_before'],.25);self.assertGreater(row['exposed_floor_fraction'],.55)
    def test_actual_removed_tile_with_actor_on_it_keeps_visible_floor_evidence(self):
        folder=ROOT/'data/v3/v3_trial_2b7d1f3388c54b26';before=cv2.imread(str(folder/'0145-v3-glove-preflight.jpg'));after=cv2.imread(str(folder/'0147-v3-glove-removal-check.jpg'));index=[0]
        def capture(label):
            frame=before if index[0]==0 else after;index[0]+=1;features=SpatialVision().entities(frame);features['frame']='synthetic:raw-removal-replay';return frame,features
        session=SimpleNamespace(root=ROOT,scope='world:1:passage:1',run_id='synthetic:replay',transition=lambda *a:None,capture=capture,check_cancel=lambda:None,preflight_enemy=lambda f:False,memory=SimpleNamespace(remember=lambda *a,**k:None),pulse=lambda a:{'metrics':{}})
        with patch('cognitive.v3.rock_glove.time.sleep',lambda *a:None):result=drill_visible(session,max_actions=1)
        row=result['tiles'][0];self.assertTrue(row['verified']);self.assertTrue(row['observed_actor_occlusions']);self.assertGreaterEqual(row['visible_tile_fraction'],.3);self.assertGreater(row['exposed_floor_fraction'],row['raw_exposed_floor_fraction']);self.assertLess(row['rock_pixels_remaining']/row['rock_pixels_before'],.25)
    def test_closed_stone_does_not_count_as_a_lowered_gate(self):
        s=SimpleNamespace(root=ROOT);frame=cv2.imread(str(ROOT/SOURCE));self.assertFalse(lowered_stone_evidence(s,frame)['verified'])
    def test_actual_lowered_stone_exposes_floor_at_the_old_closed_panel(self):
        s=SimpleNamespace(root=ROOT);frame=cv2.imread(str(ROOT/'data/v3/v3_lantern_probe_ff69eded4f7f4817/0024-v3-fixed-contact-progress.jpg'));proof=lowered_stone_evidence(s,frame);self.assertTrue(proof['verified']);self.assertGreater(proof['exposed_floor_fraction'],.9)
    def test_open_gate_route_requires_proof_from_the_same_entry(self):
        from cognitive.v3.lantern_gate import traverse_open_gate
        def retrieve(scope,kind,**kw):
            return [{'content':{'entry_token':'current'}}] if kind=='v3_active_plan' else [{'id':'old','validation':'verified','content':{'entry_token':'old'}}]
        session=SimpleNamespace(scope='world:1:passage:1',memory=SimpleNamespace(retrieve=retrieve))
        with self.assertRaisesRegex(RuntimeError,'No verified open barrier'):traverse_open_gate(session)
    def test_cached_gate_sequence_still_requires_the_measured_endpoint(self):
        from cognitive.v3.lantern_gate import traverse_open_gate
        for end,expected in [([440,820],True),([440,805],False)]:
            points=iter([[405,755],end]);planned=[];checks=[]
            f={'scene':'jogo','player':[800,445],'health':1,'frame':'fixture:game'}
            def retrieve(scope,kind,**kw):return [{'content':{'entry_token':'same'}}] if kind=='v3_active_plan' else [{'id':'gate','validation':'verified','content':{'entry_token':'same'}}]
            s=SimpleNamespace(scope='world:1:passage:1',run_id='fixture',speeds={'move':.06},segment_results=[],memory=SimpleNamespace(retrieve=retrieve,remember=lambda *a,**kw:None),map_state=lambda *a:(None,None,next(points),{'frame':'fixture:map'}),transition=lambda *a:None,capture=lambda *a:(None,f),preflight_enemy=lambda f:False,prepare_continuous=lambda *a:None,verify_continuous=lambda result,valid:checks.append(valid),backend=SimpleNamespace(release_all=lambda:None))
            s.controls=SimpleNamespace(execute_sequence=lambda actions,**kw:(planned.extend(actions) or [{'outcome':'duration_elapsed'}]))
            observer=SimpleNamespace(start=lambda:observer,close=lambda:{})
            with patch('cognitive.v3.observation.LiveObserver',return_value=observer):result=traverse_open_gate(s)
            self.assertEqual(result['verified'],expected);self.assertEqual(checks,[expected]);self.assertEqual([a['direction'] for a in planned],['right','down']);self.assertAlmostEqual(planned[0]['duration_ms'],35/.06)
    def resume_session(self,entry,point):
        record={'id':'gate-proof','validation':'verified','content':{'entry_token':'same','formerly_blocked_edge_reference':[440,802],'crossing_map_frame':'fixture:old','verified':True}}
        def retrieve(scope,kind,**kw):return [{'content':{'entry_token':entry}}] if kind=='v3_active_plan' else [record]
        return SimpleNamespace(root=ROOT,scope='world:1:passage:1',memory=SimpleNamespace(retrieve=retrieve),transition=lambda *a:None,capture=lambda *a:(None,{'frame':'fixture:game'}),map_state=lambda *a:({},None,point,{'frame':'fixture:current-map'}),held_object_kind=None)
    def test_resume_requires_same_entry_and_current_map_beyond_the_whole_gate(self):
        with patch('cognitive.v3.puzzle.arrow_visible',return_value=False),patch('cognitive.v3.puzzle.goto_room_checkpoint',side_effect=RuntimeError('must revalidate')):
            result=LanternSegment(self.resume_session('same',[442,812])).run();self.assertTrue(result['verified']);self.assertEqual(result['crossing_map_frame'],'fixture:current-map')
            for entry,point in [('different',[442,812]),('same',[442,790])]:
                with self.subTest(entry=entry,point=point),self.assertRaisesRegex(RuntimeError,'must revalidate'):LanternSegment(self.resume_session(entry,point)).run()
