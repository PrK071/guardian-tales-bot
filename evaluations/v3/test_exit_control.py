from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile,unittest,cv2,json,time
from cognitive.v3.exit_control import completed_passage_card,verified_exit_context,verify_exit_result,house_candidate
from cognitive.stage_v2 import InteractionVision
from cognitive.contracts import Observation
from cognitive.stage_v2 import completion_evidence

ROOT=Path(__file__).resolve().parents[2]

class ExitTests(unittest.TestCase):
    def test_actor_and_follower_occlusion_can_be_bypassed_without_painting_the_follower_as_floor(self):
        from cognitive.v3.exit_control import visible_exit_detour
        from cognitive.v3.exploration import visible_floor_horizon
        r=json.loads((ROOT/'evaluations/v3/fixtures/exit-obstacle/follower-occlusion.json').read_text());frame=cv2.imread(str(ROOT/r['lossless_frame']));f=r['features'];self.assertIsNone(visible_floor_horizon(frame,f,'down'));route=visible_exit_detour(frame,f)
        self.assertIsNotNone(route);self.assertGreater(abs(route['direction'][0]),.5);self.assertGreaterEqual(route['direction'][1],0);self.assertGreater(route['plan']['segments'][-1]['end'][1]-f['player'][1],100)
    def test_exit_entry_envelope_allows_a_visible_flank_but_still_requires_current_objectives(self):
        active={'entry_token':'synthetic:entry','plan_id':'synthetic:plan','states':{'lantern_puzzle':{'state':'completed','frame':'synthetic:gate','result':{'verified':True}},'final_encounter':{'state':'completed','frame':'synthetic:combat','result':{'visible_combat_ended':True}}}}
        with tempfile.TemporaryDirectory(dir=ROOT/'data/v3') as folder:
            path=Path(folder)/'map.jpg';path.write_bytes(b'synthetic map-path gate; not gameplay evidence');s=SimpleNamespace(root=ROOT,folder=Path(folder),scope='world:1:passage:1',memory=SimpleNamespace(retrieve=lambda *a,**kw:[{'content':active}]))
            context=verified_exit_context(s,[440,988],str(path.relative_to(ROOT)));self.assertTrue(context['current_entry_verified']);self.assertNotIn('stage_complete',context)
            for arrival in ([460,988],[440,929]):
                with self.subTest(arrival=arrival),self.assertRaisesRegex(RuntimeError,'No current-run'):verified_exit_context(s,arrival,str(path.relative_to(ROOT)))
            active['states']['final_encounter']['state']='pending'
            with self.assertRaisesRegex(RuntimeError,'lacks verified'):verified_exit_context(s,[440,988],str(path.relative_to(ROOT)))
    def test_raw_torch_flank_is_not_clear_just_because_floor_colours_skip_its_rim(self):
        from cognitive.lantern_vision import LanternVision
        from cognitive.v3.exploration import visible_floor_horizon
        r=json.loads((ROOT/'evaluations/v3/fixtures/exit-obstacle/blocked-flank.json').read_text());frame=cv2.imread(str(ROOT/r['lossless_frame']));f=r['features'];objects=[o for o in LanternVision(ROOT).detect(frame,f['player'],False) if o['kind']=='portable_brazier']
        self.assertTrue(objects);self.assertIsNotNone(visible_floor_horizon(frame,f,'down'));self.assertIsNone(visible_floor_horizon(frame,f,'down',extra_obstacles=objects,clearance_pixels=28))
    def test_exit_stops_on_independent_map_stagnation_instead_of_repeating_forward_holds(self):
        from cognitive.v3.exit_control import exit_forward
        from cognitive.lantern_vision import LanternVision
        r=json.loads((ROOT/'evaluations/v3/fixtures/exit-obstacle/replay.json').read_text());frame=cv2.imread(str(ROOT/r['lossless_frame']));f=r['features'];issued=[];records=[]
        session=SimpleNamespace(root=ROOT,scope='world:1:passage:1',run_id='synthetic:exit-stall',held_object_kind=None,check_cancel=lambda:None,transition=lambda *a:None,capture_live=lambda *a:(frame,f),preflight_enemy=lambda f:False,lantern_vision=LanternVision(ROOT),prepare_continuous=lambda *a:None,verify_continuous=lambda *a:None,backend=SimpleNamespace(release_all=lambda:None),controls=SimpleNamespace(move_hold=lambda *a,**kw:(issued.append(a) or {'outcome':'duration_elapsed'})),map_state=lambda *a:({},None,[425.5,975],{'frame':'synthetic:independent-map'}),memory=SimpleNamespace(remember=lambda *a,**kw:records.append(a)))
        observer=SimpleNamespace(start=lambda:observer,close=lambda:{})
        with patch('cognitive.v3.exit_control.verified_exit_context',return_value={'current_entry_verified':True}),patch('cognitive.v3.exit_control.visible_floor_horizon',return_value={'duration_ms':500}),patch('cognitive.v3.exit_control.LiveObserver',return_value=observer):
            with self.assertRaisesRegex(RuntimeError,'did not progress in the independent map'):exit_forward(session,None,None,[425.5,975],'synthetic:arrival')
        self.assertEqual(len(issued),1);self.assertEqual(records[0][1],'v3_exit_stall');self.assertTrue(records[0][3]['stagnancy_verified'])
    def test_actual_released_torch_blocks_straight_exit_but_has_checked_lateral_route(self):
        import numpy as np
        from cognitive.v3.exit_control import visible_exit_detour
        from cognitive.v3.exploration import visible_floor_horizon
        from cognitive.lantern_vision import LanternVision
        from cognitive.spatial import SpatialVision
        from cognitive.v3.segments import clear_line
        folder=ROOT/'evaluations/v3/fixtures/exit-obstacle';r=json.loads((folder/'replay.json').read_text());frame=cv2.imread(str(ROOT/r['lossless_frame']));f=r['features'];objects=LanternVision(ROOT).detect(frame,f['player'],False)
        self.assertIsNone(house_candidate(frame,f));self.assertIsNone(visible_floor_horizon(frame,f,'down'));route=visible_exit_detour(frame,f,objects)
        self.assertIsNotNone(route);self.assertGreater(abs(route['direction'][0]),.5);self.assertGreaterEqual(route['direction'][1],0);self.assertEqual(route['clearance_pixels'],28);self.assertLessEqual(route['duration_ms'],1200)
        floor=SpatialVision.floor_mask(frame);cv2.circle(floor,tuple(map(round,f['player'])),36,255,-1)
        for obj in route['observed_obstacles']:
            x,y,w,h=obj['bbox'];floor[y:y+h,x:x+w]=0
        self.assertTrue(clear_line(cv2.distanceTransform(floor,cv2.DIST_L2,5),f['player'],route['predicted_endpoint'],28,start_escape=True))
        self.assertIsNone(visible_exit_detour(np.zeros_like(frame),f,objects))
    def test_completed_raw_star_white_core_is_not_split_into_two_small_gold_fragments(self):
        proof=completed_passage_card(cv2.imread(str(ROOT/'evaluations/v3/fixtures/completed-stage-map-raw.png')),ROOT)
        self.assertTrue(proof['verified']);star=proof['star_shapes'][0];self.assertLess(star['gold_fill_fraction'],.55);self.assertEqual(star['lit_fill_fraction'],1);self.assertGreaterEqual(star['gold_pixels'],70)
    def test_known_exit_waits_through_observed_loading_before_two_real_map_checks(self):
        now=[0.];seen=[];frame=cv2.imread(str(ROOT/'evaluations/v3/fixtures/completed-stage-map.jpg'));scenes=iter(['carregando']*6+['desconhecida','mapa','mapa'])
        def observe():
            scene=next(scenes);now[0]+=2;ob=SimpleNamespace(id=str(len(seen)),scene=scene,blocked=None,text='Mapa Mundo 1 Floresta Kanterbury' if scene=='mapa' else 'Carregando',frame_path='synthetic:loading'+str(len(seen)));seen.append(ob);return ob
        runtime=SimpleNamespace(environment=SimpleNamespace(observe=observe,last_frame=frame),evidence=lambda ob:None);bot=SimpleNamespace(snapshot={'scene':'mapa','words':[]})
        with tempfile.TemporaryDirectory(dir=ROOT/'data/v3') as folder:
            marker=Path(folder)/'marker.jpg';marker.write_bytes(b'synthetic marker path; map check uses real fixture')
            session=SimpleNamespace(root=ROOT,folder=Path(folder),scope='world:1:passage:1',run_id='synthetic:loading',check_cancel=lambda:None,memory=SimpleNamespace(remember=lambda *a:None))
            with patch('cognitive.v3.exit_control.time.monotonic',side_effect=lambda:now[0]):
                result=verify_exit_result(session,runtime,bot,{'frame':str(marker.relative_to(ROOT))},{'current_entry_verified':True,'controls_issued':True})
        self.assertTrue(result['stage_complete']);self.assertEqual(len(result['result_evidence']),2);self.assertEqual(result['verification_seconds'],18);self.assertEqual([r['scene'] for r in result['observed_scenes']],['carregando']*6+['desconhecida','mapa','mapa'])
    def test_real_reward_ocr_without_spaces_is_recognized_and_requires_result_scene(self):
        from bot import Bot
        data=json.loads((ROOT/'data/v3/v3_trial_9284f3ddf8044ce2/exit-reconciliation.json').read_text())
        frame=cv2.imread(data['result']['result_observations'][0]['frame'])
        words=['RecompporGraudeEtapa','50','EtapaCompletada!','Toque em umespacovaziopara fechara tela.']
        box=[[700,300],[900,300],[900,330],[700,330]]
        bot=Bot();bot.adb=SimpleNamespace(foreground=lambda:True,capture=lambda:frame);bot.ocr=lambda f:([(box,text,.99) for text in words],None)
        _,snap=bot.observe();self.assertEqual(snap['scene'],'resultado');self.assertTrue(completion_evidence(snap))
        self.assertFalse(completion_evidence({**snap,'scene':'pausa'}));self.assertFalse(completion_evidence({**snap,'blocked':'comprar'}))
    def test_completion_uses_real_observation_frame_path_and_distinct_evidence(self):
        snapshot={'scene':'resultado','words':[{'text':'EtapaCompletada!'}]}
        def observe():
            index=len(seen);ob=Observation(str(index),time.time(),'resultado',.98,'unknown',None,'EtapaCompletada!',{},frame_path='synthetic:result'+str(index));seen.append(ob);return ob
        seen=[];records=[]
        s=SimpleNamespace(root=ROOT,folder=ROOT/'data/v3',scope='world:1:passage:1',run_id='synthetic:test',check_cancel=lambda:None,memory=SimpleNamespace(remember=lambda *a:records.append(a)))
        runtime=SimpleNamespace(environment=SimpleNamespace(observe=observe,last_frame=None),evidence=lambda ob:None)
        result=verify_exit_result(s,runtime,SimpleNamespace(snapshot=snapshot),None,{})
        self.assertEqual(len(result['result_evidence']),2);self.assertEqual(result['result_observations'][1]['frame'],'synthetic:result1')
        runtime.environment.observe=lambda:seen[0]
        self.assertIsNone(verify_exit_result(s,runtime,SimpleNamespace(snapshot=snapshot),None,{},seconds=.005))
    def test_actual_final_house_requires_the_observed_interaction_glyph(self):
        frame=cv2.imread(str(ROOT/'data/v3/v3_trial_945e38a16c4141ba/0168-v3-exit-forward-after.jpg'))
        marker=house_candidate(frame,{'player':[800,445]});self.assertIsNotNone(marker);self.assertAlmostEqual(marker['point'][0],839,delta=4);self.assertTrue(InteractionVision(ROOT).affordance(frame));self.assertFalse(InteractionVision.dialogue(frame))
    def test_original_uncompleted_passage_card_is_not_a_completion(self):
        proof=completed_passage_card(cv2.imread(str(ROOT/'data/v2/recovery-world.png')),ROOT)
        self.assertGreater(proof['card_score'],.95);self.assertFalse(proof['verified'])
    def test_actual_completed_zoomed_card_is_identified_with_filled_star(self):
        proof=completed_passage_card(cv2.imread(str(ROOT/'data/v2/v2_preparation_fb2e0971b4ec46bb/000-mapa.jpg')),ROOT)
        self.assertTrue(proof['verified']);self.assertGreater(proof['card_score'],.90);self.assertTrue(proof['star_shapes'])
    def test_missing_current_entry_cannot_authorize_exit_completion(self):
        s=SimpleNamespace(scope='world:1:passage:1',memory=SimpleNamespace(retrieve=lambda *a,**kw:[]))
        with self.assertRaisesRegex(RuntimeError,'No active stage entry'):verified_exit_context(s,[425,938],'fixture:map')
    def test_filled_map_star_without_actual_house_and_movement_is_insufficient(self):
        ob=SimpleNamespace(id='synthetic:map',frame_path='synthetic:map',scene='mapa',blocked=None,text='Mapa Mundo 1 Floresta Kanterbury')
        runtime=SimpleNamespace(environment=SimpleNamespace(observe=lambda:ob,last_frame=None),evidence=lambda ob:None)
        bot=SimpleNamespace(snapshot={'scene':'mapa','words':[]})
        with tempfile.TemporaryDirectory(dir=ROOT/'data/v3') as folder:
            s=SimpleNamespace(root=ROOT,folder=Path(folder),check_cancel=lambda:None)
            with patch('cognitive.v3.exit_control.completed_passage_card',return_value={'verified':True}):
                self.assertIsNone(verify_exit_result(s,runtime,bot,None,{'current_entry_verified':True,'controls_issued':True},seconds=.005))
                marker=Path(folder)/'marker.jpg';marker.write_bytes(b'synthetic test file, not gameplay evidence')
                house={'frame':str(marker.relative_to(ROOT))}
                self.assertIsNone(verify_exit_result(s,runtime,bot,house,{'current_entry_verified':True,'controls_issued':False},seconds=.005))
