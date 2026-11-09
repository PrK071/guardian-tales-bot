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
    def test_verified_immediate_pair_is_reused_without_the_real_redundant_failure_frame(self):
        import json,numpy as np
        from cognitive.v3.local_observation import motion_after_pulse
        r=json.loads((ROOT/'evaluations/v3/fixtures/fixed-base-motion/redundant-capture-replay.json').read_text());row=r['row'];row['after']['at']=time.time();frame=np.zeros((4,4,3),np.uint8)
        c=SimpleNamespace(check=lambda:None,observe=lambda *a:self.fail('A fresh completed observation must not be recaptured'));s=SimpleNamespace(last_frame=frame,last_features=row['after'])
        with patch('cognitive.v3.local_observation.SpatialVision.motion',side_effect=AssertionError('Same exact pair already measured')):after,f,motion=motion_after_pulse(s,c,row,frame,row['before'],'synthetic:unused')
        self.assertIs(after,frame);self.assertEqual(f['frame'],row['after']['frame']);self.assertNotEqual(f['frame'],r['redundant_after']['frame']);self.assertEqual(motion['confidence'],.514);self.assertTrue(row['metrics']['post_action_observation_reused'])
    def test_stale_threat_and_health_conditions_keep_the_observation_guards(self):
        import json,copy,numpy as np
        from cognitive.v3.local_observation import motion_after_pulse
        row=json.loads((ROOT/'evaluations/v3/fixtures/fixed-base-motion/redundant-capture-replay.json').read_text())['row'];frame=np.zeros((4,4,3),np.uint8)
        for changes in ({'at':time.time()-2},{'at':time.time(),'combat_present':True},{'at':time.time(),'health':.2}):
            f={**copy.deepcopy(row['after']),**changes};s=SimpleNamespace(last_frame=frame,last_features=f)
            def guarded(*a):raise RuntimeError('fresh observation guard')
            with self.subTest(changes=changes),self.assertRaisesRegex(RuntimeError,'observation guard'):motion_after_pulse(s,SimpleNamespace(check=lambda:None,observe=guarded),row,frame,row['before'],'synthetic:guard')
    def test_motion_from_a_different_before_frame_is_recomputed(self):
        import json,numpy as np
        from cognitive.v3.local_observation import motion_after_pulse
        row=json.loads((ROOT/'evaluations/v3/fixtures/fixed-base-motion/redundant-capture-replay.json').read_text())['row'];row['after']['at']=time.time();frame=np.zeros((4,4,3),np.uint8);s=SimpleNamespace(last_frame=frame,last_features=row['after']);measured={'confidence':.42}
        with patch('cognitive.v3.local_observation.SpatialVision.motion',return_value=measured) as motion:_,_,result=motion_after_pulse(s,SimpleNamespace(check=lambda:None),row,frame,{**row['before'],'frame':'synthetic:different-before'},'unused')
        self.assertIs(result,measured);self.assertEqual(motion.call_count,1);self.assertFalse(row['metrics']['post_action_motion_pair_reused'])
    def test_current_fixed_base_recovers_real_diagonal_rock_access_translation(self):
        import json
        from cognitive.v3.fixed_lanterns import fixed_base_motion
        r=json.loads((ROOT/'evaluations/v3/fixtures/fixed-base-motion/rock-access-replay.json').read_text());self.assertEqual(r['old_global_motion']['confidence'],0)
        m=fixed_base_motion(r['before_features'],r['after_features'],r['action']['direction'],r['action']['ms'])
        self.assertIsNotNone(m);self.assertAlmostEqual(m['background_dx'],-249,delta=2);self.assertAlmostEqual(m['background_dy'],249,delta=2);self.assertGreaterEqual(m['confidence'],.84)
    def test_current_fixed_lamp_recovers_the_large_translation_missed_by_global_motion(self):
        import json
        from cognitive.v3.fixed_lanterns import fixed_base_motion
        r=json.loads((ROOT/'evaluations/v3/fixtures/fixed-base-motion/replay.json').read_text());self.assertEqual(r['old_global_motion']['confidence'],0)
        motion=fixed_base_motion(r['before_features'],r['after_features'],r['action']['direction'],r['action']['ms'])
        self.assertIsNotNone(motion);self.assertAlmostEqual(motion['background_dx'],-300,delta=3);self.assertAlmostEqual(motion['background_dy'],0,delta=3);self.assertGreaterEqual(motion['confidence'],.84);self.assertTrue(motion['moved'])
    def test_fixed_base_motion_rejects_wrong_direction_impossible_distance_and_ambiguity(self):
        import json,copy
        from cognitive.v3.fixed_lanterns import fixed_base_motion
        r=json.loads((ROOT/'evaluations/v3/fixtures/fixed-base-motion/replay.json').read_text());before=r['before_features'];after=r['after_features']
        self.assertIsNone(fixed_base_motion(before,after,'left',670));self.assertIsNone(fixed_base_motion(before,after,'right',80));self.assertIsNone(fixed_base_motion(before,{**after,'puzzle_objects':[]},'right',670))
        ambiguous=copy.deepcopy(after);obj=copy.deepcopy(next(o for o in after['puzzle_objects'] if o['kind']=='standing_lantern_unlit'));obj['bbox'][0]+=80;ambiguous['puzzle_objects'].append(obj)
        self.assertIsNone(fixed_base_motion(before,ambiguous,'right',670))
    def test_exact_raw_pickup_frame_gets_safe_fine_grid_connector_without_relaxing_clearance(self):
        import json,hashlib,math
        from cognitive.puzzle_control import BombRockController,DIRECTIONS
        from cognitive.v3.segments import SegmentPlanner,clear_line
        folder=ROOT/'evaluations/v3/fixtures/raw-torch-approach';r=json.loads((folder/'replay.json').read_text());frame=cv2.imread(str(ROOT/r['lossless_frame']));self.assertEqual(hashlib.sha256(frame.tobytes()).hexdigest(),r['pixels_bgr_sha256']);f=r['features'];obj=next(o for o in f['puzzle_objects'] if o['kind']=='portable_brazier');target=LanternController.foot(obj);original=SegmentPlanner.plan;calls=[]
        def plan(planner,state,target,**kw):calls.append((state,kw));return original(planner,state,target,**kw)
        with patch.object(SegmentPlanner,'plan',plan):heading,ms=BombRockController.local_approach(frame,f,target)
        self.assertTrue(calls);self.assertEqual(calls[0][1]['margin'],28);self.assertGreaterEqual(ms,80);self.assertLessEqual(ms,300)
        state=calls[0][0];vx,vy=DIRECTIONS[heading];norm=math.hypot(vx,vy);end=[f['player'][0]+vx/norm*ms*.44,f['player'][1]+vy/norm*ms*.44]
        self.assertTrue(clear_line(cv2.distanceTransform(state['floor'],cv2.DIST_L2,5),f['player'],end,28,start_escape=True))
    def room_detour_replay(self,revisit=False):
        import json
        from cognitive.map_anchor import SpawnMapAnchor
        from cognitive.map_navigation import PauseMap
        folder=ROOT/'evaluations/v3/fixtures/room-detour';data=json.loads((folder/'replay.json').read_text());a=data['anchor'];anchor=SpawnMapAnchor(cv2.imread(str(ROOT/a['path']),0),a['origin'],a['spawn_point']);checkpoints=[]
        for name in data['maps']:
            state=PauseMap().parse(cv2.imread(str(folder/name)));alignment=anchor.locate(state);self.assertGreater(alignment['score'],.98);checkpoints.append((state,alignment,anchor.project(state['player'],alignment),{'frame':str((folder/name).relative_to(ROOT))}))
        if revisit:checkpoints[1]=checkpoints[0]
        actions=data['actions'];index=[0];records=[];issued=[];maps=iter(checkpoints)
        def check():
            if index[0]==len(actions):raise InterruptedError('replay stopped after first map checkpoint')
        def capture(label):
            row=actions[index[0]];return cv2.imread(str(ROOT/row['before']['frame'])),row['before']
        def pulse(action):
            row=actions[index[0]];issued.append(action);index[0]+=1;session.last_features=row['after'];return row
        session=SimpleNamespace(scope='world:1:passage:1',run_id='fixture:room-detour',speeds={'move':.059537465550086245},map_state=lambda *a:next(maps),check_cancel=check,transition=lambda *a:None,capture=capture,preflight_enemy=lambda f:False,pulse=pulse,memory=SimpleNamespace(remember=lambda *a,**kw:records.append(a)),last_features=actions[0]['before'])
        return session,data,records,issued,checkpoints
    def test_real_floor_detour_may_temporarily_increase_goal_distance_without_completing_goal(self):
        from cognitive.v3.room_navigation import navigate_room
        session,data,records,issued,points=self.room_detour_replay()
        with self.assertRaisesRegex(InterruptedError,'first map checkpoint'):navigate_room(session,data['target_reference'])
        self.assertEqual([a.args['direction'] for a in issued],['left','up','right']);self.assertEqual(len(records),1);self.assertEqual(records[0][1],'v3_room_detour');proof=records[0][3];self.assertGreater(proof['goal_error_after'],proof['goal_error_before']);self.assertFalse(proof['goal_reached'])
    def test_room_detour_still_rejects_revisited_map_pose_despite_apparent_visual_motion(self):
        from cognitive.v3.room_navigation import navigate_room
        session,data,records,issued,points=self.room_detour_replay(revisit=True)
        with self.assertRaisesRegex(RuntimeError,'did not improve'):navigate_room(session,data['target_reference'])
        self.assertFalse(records);self.assertEqual(len(issued),3)
    def test_glove_mask_tracks_the_removed_right_column_without_the_intact_left_neighbour(self):
        before=cv2.imread(str(ROOT/'evaluations/v3/fixtures/stone-column-before.jpg'));after=cv2.imread(str(ROOT/'evaluations/v3/fixtures/stone-column-after.jpg'));index=[0]
        def capture(label):
            frame=before if index[0]==0 else after;index[0]+=1;f=SpatialVision().entities(frame);f['frame']='fixture:stone-column-'+str(index[0]);return frame,f
        session=SimpleNamespace(root=ROOT,scope='world:1:passage:1',run_id='fixture:stone-column',transition=lambda *a:None,capture=capture,check_cancel=lambda:None,preflight_enemy=lambda f:False,memory=SimpleNamespace(remember=lambda *a,**kw:None),pulse=lambda a:{'metrics':{}})
        with patch('cognitive.v3.rock_glove.time.sleep',lambda *a:None):result=drill_visible(session,max_actions=1)
        row=result['tiles'][0];self.assertTrue(row['verified']);self.assertGreaterEqual(row['tile_bbox'][0],765);self.assertLess(row['rock_pixels_remaining']/row['rock_pixels_before'],.25);self.assertGreater(row['exposed_floor_fraction'],.55)
    def test_adjacent_wall_torch_gets_one_facing_pulse_and_still_needs_pickup_glyph(self):
        frame=cv2.imread(str(ROOT/'evaluations/v3/fixtures/adjacent-torch-wall-facing.jpg'));vision=LanternVision(ROOT);features=SpatialVision().entities(frame);features.update(frame='fixture:wall-torch',puzzle_objects=vision.detect(frame,features['player'],False));actions=[]
        motion={'confidence':1,'background_dx':0,'background_dy':0,'effective_dx':0,'effective_dy':0}
        session=SimpleNamespace(root=ROOT,scope='world:1:passage:1',lantern_vision=vision,transition=lambda *a:None,check_cancel=lambda:None,pulse=lambda a:(actions.append(a) or {'metrics':{'motion':motion}}))
        c=LanternController(session);c.observe=lambda label:(frame,features);c.event=lambda *a,**kw:None
        with patch('cognitive.lantern_control.BombRockController.local_approach',side_effect=RuntimeError('No direct local segment with observed player clearance')):
            with self.assertRaisesRegex(RuntimeError,'No direct local segment'):c.approach('portable_brazier')
        self.assertEqual(len(actions),1);self.assertEqual(actions[0].op,'move');self.assertEqual(actions[0].args,{'direction':'left','ms':80})
    def test_puzzle_restores_planned_view_after_glove_lunge_before_searching_for_torch(self):
        routes=[];observations=[];obj={'kind':'standing_lantern_unlit','bbox':[1200,400,67,91]};features={'frame':'fixture:room','puzzle_objects':[obj]}
        session=SimpleNamespace(transition=lambda *a:None,capture=lambda *a:(None,features),scope='world:1:passage:1',held_object_kind=None,memory=SimpleNamespace(retrieve=lambda *a,**kw:[]))
        controller=SimpleNamespace(observe=lambda label:(observations.append(label) or (None,features)),objects=LanternController.objects,pickup=lambda:(_ for _ in ()).throw(RuntimeError('pickup reached after restored view')))
        with patch('cognitive.v3.puzzle.LanternController',return_value=controller),patch('cognitive.v3.puzzle.arrow_visible',return_value=False),patch('cognitive.v3.puzzle.goto_room_checkpoint',side_effect=lambda s,p:routes.append(p)),patch('cognitive.v3.puzzle.ensure_lantern_access',return_value={'verified':True,'tiles':[{'verified':True}]}):
            with self.assertRaisesRegex(RuntimeError,'pickup reached'):LanternSegment(session).run()
        self.assertEqual(routes,[[426,713],[426,713]]);self.assertEqual(observations[-1],'v3-lantern-return-after-glove')
    def test_room_uses_one_verified_removed_tile_escape_before_retrying_local_route(self):
        from cognitive.v3.room_navigation import goto_room_checkpoint
        session=SimpleNamespace(navigate_to=lambda *a,**kw:{'verified':False,'progress_verified':False})
        error=RuntimeError('No direct local segment with observed player clearance')
        with patch('cognitive.v3.room_navigation.navigate_room',side_effect=[error,{'verified':True}]) as route,patch('cognitive.v3.rock_glove.escape_cleared_tile',return_value={'verified':True}) as escape:
            self.assertTrue(goto_room_checkpoint(session,[426,713])['verified']);self.assertEqual(route.call_count,2);escape.assert_called_once()
        with patch('cognitive.v3.room_navigation.navigate_room',side_effect=error) as route,patch('cognitive.v3.rock_glove.escape_cleared_tile',return_value={'verified':True}) as escape:
            with self.assertRaisesRegex(RuntimeError,'No direct local segment'):goto_room_checkpoint(session,[426,713])
            self.assertEqual(route.call_count,2);escape.assert_called_once()
    def test_burning_ground_brazier_left_of_camera_centre_remains_visible_outside_minimap(self):
        frame=cv2.imread(str(ROOT/'evaluations/v3/fixtures/ground-brazier-left-viewport.jpg'));vision=LanternVision(ROOT);features=SpatialVision().entities(frame)
        objects=[o for o in vision.detect(frame,features['player'],False) if o['kind']=='portable_brazier']
        self.assertEqual(len(objects),1);self.assertEqual(objects[0]['bbox'],[311,396,110,106]);self.assertGreater(objects[0]['confidence'],.95)
        self.assertGreater(objects[0]['bbox'][1],230)
    def registered_stone_fixture(self):
        frame=cv2.imread(str(ROOT/'evaluations/v3/fixtures/registered-stone-occluded-actor.jpg'))
        features=SpatialVision().entities(frame);features['frame']='fixture:ebd17a2d61694c04/0487';features['puzzle_objects']=LanternVision(ROOT).detect(frame,features['player'],False)
        known=[{'id':'memory_87f427f86aeb47de','validation':'verified','content':{'fixed_base_reference':[478.3957432496181,766.6900030493115]}}]
        rock=min((e for e in features['entities'] if e['kind']=='rock_obstacle_candidate'),key=lambda e:abs(e['bbox'][0]-1039))
        return frame,features,known,rock
    def test_registered_stone_side_uses_observed_lamp_and_independent_map_with_occluded_actor(self):
        from cognitive.v3.rock_glove import registered_column_goal
        frame,features,known,rock=self.registered_stone_fixture()
        proof=registered_column_goal([426.7323943661973,770.1267605633802],features['puzzle_objects'],known,rock,.44/.059537465550086245,features['player'])
        self.assertEqual(proof['candidates'][0]['face'],'right');self.assertAlmostEqual(proof['candidates'][0]['target'][0],449.8662,places=3);self.assertAlmostEqual(proof['candidates'][0]['target'][1],765.5613,places=3)
        self.assertGreater(abs(features['player'][1]-proof['associated_actor_pixel'][1]),30)
    def test_registered_stone_side_rejects_unknown_uncertain_or_conflicting_landmarks(self):
        from cognitive.v3.rock_glove import registered_column_goal
        _,features,known,rock=self.registered_stone_fixture()
        conflict={'id':'different-registration','validation':'verified','content':{'fixed_base_reference':[484,766.6900030493115]}}
        for rows in ([],[{**known[0],'validation':'uncertain'}],known+[conflict]):
            with self.subTest(rows=rows),self.assertRaisesRegex(RuntimeError,'unambiguous|disagree'):
                registered_column_goal([426.7323943661973,770.1267605633802],features['puzzle_objects'],rows,rock,.44/.059537465550086245,features['player'])
    def test_registered_side_still_requires_current_glove_and_verified_route(self):
        from cognitive.v3.rock_glove import approach_registered_column
        import numpy as np
        frame,features,known,rock=self.registered_stone_fixture();actions=[];proofs=[]
        session=SimpleNamespace(scope='world:1:passage:1',run_id='fixture',backend=SimpleNamespace(held={}),speeds={'move':.059537465550086245},controls=SimpleNamespace(actions=[]),memory=SimpleNamespace(retrieve=lambda *a,**kw:known,remember=lambda *a,**kw:proofs.append(a)),map_state=lambda *a:({'floor':np.ones((900,1600),np.uint8)*255},{'scale':1},[426.7323943661973,770.1267605633802],{'frame':'fixture:map'}),raw_target=lambda point,alignment:point,transition=lambda *a:None,navigate_to=lambda *a,**kw:{'verified':True},pulse=actions.append)
        controller=SimpleNamespace(observe=lambda *a:(frame,features))
        with patch('cognitive.v3.rock_glove.glove_visible',return_value=False),patch('cognitive.v3.rock_glove.drill_visible') as drill:
            with self.assertRaisesRegex(RuntimeError,'affordance absent'):approach_registered_column(session,controller,frame,features,rock)
            drill.assert_not_called();self.assertEqual(len(actions),1);self.assertEqual(actions[0].args['ms'],80);self.assertFalse(proofs)
        session.navigate_to=lambda *a,**kw:{'verified':False,'progress_verified':False};actions.clear()
        with patch('cognitive.v3.rock_glove.drill_visible') as drill:
            with self.assertRaisesRegex(RuntimeError,'did not progress'):approach_registered_column(session,controller,frame,features,rock)
            drill.assert_not_called();self.assertFalse(actions)
    def test_registered_side_keeps_clearance_when_nearest_standoffs_touch_map_edge(self):
        from cognitive.v3.rock_glove import approach_registered_column
        import numpy as np
        frame,features,known,rock=self.registered_stone_fixture();floor=np.zeros((900,1600),np.uint8);floor[:,:456]=255;routes=[]
        def navigate(target,**kw):routes.append(target);return {'verified':True}
        session=SimpleNamespace(scope='world:1:passage:1',run_id='fixture',backend=SimpleNamespace(held={}),speeds={'move':.059537465550086245},controls=SimpleNamespace(actions=[]),memory=SimpleNamespace(retrieve=lambda *a,**kw:known,remember=lambda *a,**kw:None),map_state=lambda *a:({'floor':floor},{'scale':1},[426.7323943661973,770.1267605633802],{'frame':'fixture:map'}),raw_target=lambda point,alignment:point,transition=lambda *a:None,navigate_to=navigate)
        controller=SimpleNamespace(observe=lambda *a:(frame,features))
        with patch('cognitive.v3.rock_glove.glove_visible',return_value=True),patch('cognitive.v3.rock_glove.drill_visible',return_value={'verified':True}) as drill:
            result=approach_registered_column(session,controller,frame,features,rock)
        self.assertTrue(result['verified']);self.assertEqual(result['registered_approach']['chosen']['standoff_reference'],14);self.assertAlmostEqual(routes[0][0],441.8662,places=3);drill.assert_called_once()
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
