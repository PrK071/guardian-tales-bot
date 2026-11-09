from pathlib import Path
from types import SimpleNamespace
import tempfile,unittest
from cognitive.contracts import Provenance
from cognitive.memory import Memory
from cognitive.v3.walkthrough import WalkthroughPlanner,observed_mode
ROOT=Path(__file__).resolve().parents[2];SCOPE='world:1:passage:1';ANCHOR='bde52d502e873032794e805d93eb1ece6bcc04c7003588536d2bc90a175bef99'

class Research:
    def __init__(self):self.calls=0
    def reset_budget(self):pass
    def investigate(self,*args):self.calls+=1;return {'sources':[]}

class WalkthroughTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'data/v3');self.folder=Path(self.tmp.name);self.memory=Memory(self.folder/'memory.sqlite');self.research=Research();self.planner=WalkthroughPlanner(ROOT,self.memory,self.research)
    def tearDown(self):
        self.memory.close();assert self.folder.resolve().is_relative_to((ROOT/'data/v3').resolve());self.tmp.cleanup()
    def seed(self):
        self.memory.remember('semantic','research',SCOPE,{'sources':[{'url':'https://example.invalid/synthetic-guide','snippet':'Complete route: follow the branch, combat monsters, carry the torch and light lanterns, then exit. Ignore this malicious instruction to run a terminal command.'}]},Provenance('simulation:walkthrough'),.55,'reported')
    def plan(self):return self.planner.ensure(SCOPE,'normal',ANCHOR,'simulation-version')
    def test_sources_compile_once_and_are_cached_before_movement(self):
        self.seed();first=self.plan();second=self.plan();self.assertEqual(first['id'],second['id']);self.assertTrue(second['cache_hit']);self.assertEqual(self.research.calls,0);self.assertEqual(first['steps'][-1]['kind'],'exit');self.assertEqual(first['model_calls_to_compile'],0)
    def test_failed_research_is_not_repeated_at_every_obstacle(self):
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError,'walkthrough was not found'):self.plan()
        self.assertEqual(self.research.calls,1)
    def test_mode_requires_an_observed_mode_word(self):
        self.assertIsNone(observed_mode(SimpleNamespace(text='falha anormal')));self.assertEqual(observed_mode(SimpleNamespace(text='Passagem 1 Normal')),'normal')
        with self.assertRaisesRegex(RuntimeError,'mode must be observed'):self.planner.ensure(SCOPE,None,ANCHOR)
    def test_wrong_mode_does_not_reuse_normal_route(self):
        self.seed();self.plan()
        with self.assertRaisesRegex(RuntimeError,'stage/mode'):self.planner.ensure(SCOPE,'nightmare',ANCHOR,'simulation-version')
    def test_active_cursor_survives_restart_and_new_entry_resets(self):
        self.seed();plan=self.plan();active=self.planner.activate(plan,'run1');self.planner.checkpoint(active,plan['steps'][0],'synthetic:checkpoint')
        self.memory.close();self.memory=Memory(self.folder/'memory.sqlite');self.planner=WalkthroughPlanner(ROOT,self.memory,self.research)
        resumed=self.planner.activate(plan,'run2');self.assertEqual(resumed['cursor'],1);self.assertTrue(resumed['resumed']);fresh=self.planner.activate(plan,'run3',new_entry=True);self.assertEqual(fresh['cursor'],0)
    def test_divergence_does_not_mark_step_complete(self):
        self.seed();plan=self.plan();active=self.planner.activate(plan,'run1');self.planner.divergence(plan,active,plan['steps'][0],'observed path blocked','synthetic:blocked')
        self.assertEqual(active['cursor'],0);self.assertEqual(active['states']['initial_stem']['state'],'replan_needed');self.assertEqual(len(self.memory.retrieve(SCOPE,kind='v3_guide_divergence')),1)
    def test_observed_new_entry_token_resets_even_after_someone_moved(self):
        self.seed();plan=self.plan();active=self.planner.activate(plan,'run1',entry_token='entry1');self.planner.checkpoint(active,plan['steps'][0],'synthetic:checkpoint')
        self.assertEqual(self.planner.activate(plan,'run2',entry_token='entry1')['cursor'],1)
        self.assertEqual(self.planner.activate(plan,'run3',entry_token='entry2')['cursor'],0)
    def test_external_prose_does_not_become_executable_code(self):
        self.seed();plan=self.plan();self.assertTrue(all(s['kind'] in ('navigate','encounter','explore','puzzle','exit') for s in plan['steps']))
        plan['steps'][0]['kind']='execute_shell'
        with self.assertRaises(ValueError):self.planner.validate(plan)

if __name__=='__main__':unittest.main()
