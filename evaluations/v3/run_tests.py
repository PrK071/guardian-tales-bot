from pathlib import Path
import json,sys,time,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from evaluations.v3.test_continuous import ContinuousTests
from evaluations.v3.test_combat import CombatTests
from evaluations.v3.test_segments import SegmentTests
from evaluations.v3.test_walkthrough import WalkthroughTests
from evaluations.v3.test_historical_enemies import HistoricalEnemies
from evaluations.v3.test_video import VideoTests
from evaluations.v3.test_stage import StageTests
from evaluations.v3.test_exploration import ExplorationTests
from evaluations.v3.test_threats import ThreatTests
from evaluations.v3.test_lantern_tracking import LanternTrackingTests
from evaluations.v3.test_lantern_flow import LanternFlowTests
from evaluations.v3.test_exit_control import ExitTests

groups={};success=True
for cls,name in ((ContinuousTests,'simulated_input_contracts'),(CombatTests,'simulated_combat_states'),(SegmentTests,'geometry_and_historical_map'),(WalkthroughTests,'persistent_walkthroughs'),(HistoricalEnemies,'historical_enemy_detection'),(VideoTests,'stream_protocol_and_decoder'),(StageTests,'high_level_execution'),(ExplorationTests,'visible_frontier_horizons'),(ThreatTests,'distant_threat_confirmation'),(LanternTrackingTests,'real_held_object_tracking'),(LanternFlowTests,'real_lantern_tool_and_gate_evidence'),(ExitTests,'current_entry_exit_completion_guards')):
    start=time.perf_counter()
    with (ROOT/f'logs/v3-tests-{name}.txt').open('w',encoding='utf-8') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
    groups[name]={'tests':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors),'failures':[(str(case),message) for case,message in result.failures+result.errors],'duration_ms':(time.perf_counter()-start)*1000};success=success and result.wasSuccessful()
report={'groups':groups,'all_passed':success,'gameplay_proven_by_these_tests':False}
(ROOT/'evaluations/v3/tests.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report));raise SystemExit(0 if success else 1)
