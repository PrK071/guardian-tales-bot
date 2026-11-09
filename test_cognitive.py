from __future__ import annotations
from dataclasses import replace
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import json, math, os, sqlite3, subprocess, sys, tempfile, threading, time, unittest
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'evaluations'))
from harness import ScenarioEnvironment, FixtureTransport
from cognitive.advisor import HttpAdvisor
from cognitive.contracts import Action, Provenance, State, Task
from cognitive.memory import Memory
from cognitive.perception import Interpreter
from cognitive.planning import Reflector, StrategicPlanner, TaskPlanner
from cognitive.research import ResearchEngine, public_url, TextExtractor
from cognitive.runtime import CognitiveRuntime
import cv2
import numpy as np

SCENARIO={'id':'test','initial_scene':'jogo','known_stage':True,'stuck':False,'enemy':False,'clear_after':2,'cycles':15}

class MemoryAndRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'evaluations'); self.directory=Path(self.temp.name)
        self.memory=Memory(self.directory/'memory.sqlite')
    def tearDown(self): self.memory.close(); self.temp.cleanup()
    def runtime(self,**overrides):
        env=ScenarioEnvironment({**SCENARIO,**overrides})
        research=ResearchEngine(self.memory,self.directory/'missing.json',FixtureTransport())
        return CognitiveRuntime(env,self.memory,research),env
    def test_survives_reopen_and_context_excludes_other_stages(self):
        self.memory.remember('semantic','puzzle','world:1:stage:2',{'answer':'hypothesis'},Provenance('https://example.org'),.4,'reported')
        self.memory.remember('semantic','puzzle','world:2:stage:1',{'answer':'unrelated'},Provenance('other'),.7,'reported')
        self.memory.close(); self.memory=Memory(self.directory/'memory.sqlite')
        rows=self.memory.retrieve('world:1:stage:2')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['validation'],'reported'); self.assertIn('captured_at',rows[0]['provenance'])
    def test_task_has_verifiable_contract_and_dependencies(self):
        planner=TaskPlanner();goal=self.memory.goal('test');ob=ScenarioEnvironment(SCENARIO).observe()
        root=planner.task(goal,'complete_stage','root',ob.scope,{'stage_clear':True});self.memory.save_task(root)
        tasks=planner.decompose(goal,ob,{'strategy':'known_route','route':ScenarioEnvironment(SCENARIO).route_candidates(ob)[0]},root.id)
        for task in tasks:self.memory.save_task(task)
        self.assertTrue(all(t.success and t.preconditions and t.recovery and t.max_attempts for t in tasks))
        self.assertEqual(tasks[2].dependencies,[tasks[1].id])
    def test_dependency_cycle_rejected_transactionally(self):
        goal=self.memory.goal('cycle');planner=TaskPlanner()
        a=planner.task(goal,'test','a','unknown',{'ok':True});self.memory.save_task(a)
        b=planner.task(goal,'test','b','unknown',{'ok':True},dependencies=[a.id]);self.memory.save_task(b)
        a.dependencies=[b.id]
        with self.assertRaisesRegex(ValueError,'Cyclic'):self.memory.save_task(a)
        self.assertEqual(self.memory.tasks(goal)[0].dependencies,[])
    def test_successful_dispatch_without_effect_is_not_success(self):
        runtime,env=self.runtime(stuck=True)
        report=runtime.run(max_cycles=8,max_seconds=10)
        self.assertEqual(report['outcome'],'blocked');self.assertEqual(len([action for action in env.inputs if action.op=='move']),1)
        self.assertGreaterEqual(report['metrics']['replans'],1)
        self.assertFalse(any(t.kind=='complete_stage' and t.state==State.COMPLETED for t in self.memory.tasks(report['goal_id'])))
    def test_previous_failure_influences_next_session(self):
        runtime,env=self.runtime(stuck=True); first=runtime.run(max_cycles=8,max_seconds=10)
        next_runtime,next_env=self.runtime(stuck=True); second=next_runtime.run(max_cycles=5,max_seconds=10)
        self.assertEqual(len([action for action in next_env.inputs if action.op=='move']),0)
        self.assertEqual(first['goal_id'],second['goal_id'])
    def test_verified_strategy_is_retrieved_by_future_planner(self):
        env=ScenarioEnvironment(SCENARIO);ob=env.observe()
        memory_id=self.memory.remember('semantic','validated_strategy',ob.scope,{'approach':'route:simulated_route'},Provenance('test',evidence_ids=[ob.id]),.95,'verified')
        decision=StrategicPlanner().choose(ob,self.memory.retrieve(ob.scope),env.route_candidates(ob))
        self.assertIn(memory_id,decision['memory_reused'])
    def test_decomposition_executes_and_requires_two_result_observations(self):
        runtime,env=self.runtime(known_stage=False)
        report=runtime.run(max_cycles=15,max_seconds=10)
        self.assertEqual(report['outcome'],'stage_complete')
        root=next(t for t in self.memory.tasks(report['goal_id']) if t.kind=='complete_stage')
        self.assertEqual(root.state,State.COMPLETED);self.assertGreaterEqual(len(root.evidence),4)
        self.assertNotEqual(self.memory.goals()[0]['state'],State.COMPLETED) # story not proven
    def test_protected_ui_sends_no_inputs(self):
        runtime,env=self.runtime(initial_scene='bloqueada')
        self.assertEqual(runtime.run(max_cycles=4,max_seconds=10)['outcome'],'blocked');self.assertEqual(env.inputs,[])
    def test_manual_stop_sends_no_inputs_and_releases_lease(self):
        runtime,env=self.runtime();cancel=threading.Event();cancel.set()
        self.assertEqual(runtime.run(max_cycles=4,max_seconds=10,cancel=cancel)['outcome'],'interrupted')
        self.assertEqual(env.inputs,[]);self.assertTrue(self.memory.acquire('other'));self.memory.release('other')
    def test_concurrent_executor_refused(self):
        runtime,env=self.runtime();self.memory.acquire('existing')
        with self.assertRaisesRegex(RuntimeError,'Another'):runtime.run(max_cycles=2,max_seconds=10)
        self.assertEqual(env.inputs,[]);self.memory.release('existing')
    def test_changed_stage_requires_replan(self):
        runtime,env=self.runtime();goal=runtime.open_goal();saved=env.observe();self.memory.checkpoint(goal,saved,{})
        env.scope='world:2:stage:1'; current=env.observe()
        runtime.reconcile(current)
        rows=self.memory.retrieve(current.scope,kind='reconciliation')
        self.assertEqual(rows[0]['content']['status'],'replan')
    def test_unknown_fresh_stage_not_assumed_from_checkpoint(self):
        runtime,env=self.runtime();goal=runtime.open_goal();self.memory.checkpoint(goal,env.observe(),{})
        env.known=False; current=env.observe();runtime.reconcile(current)
        self.assertTrue(runtime.reconcile_needed)
        self.assertIsNone(current.stage)
    def test_uncertain_command_not_repeated_after_reconciliation(self):
        runtime,env=self.runtime();goal=runtime.open_goal();ob=env.observe();self.memory.observe(ob)
        root=self.memory.tasks(goal)[0]
        task=TaskPlanner().task(goal,'route_step','uncertain move',ob.scope,{'checkpoint':'position2'},parent_id=root.id,data={'action':{'op':'move','direction':'right','ms':300}},max_attempts=1)
        self.memory.save_task(task);operation=self.memory.prepare(goal,task.id,{'op':'move'},ob.id)
        self.memory.operation(operation,'issued');self.memory.checkpoint(goal,ob,{'operation':operation})
        runtime.reconcile(env.observe())
        recovered=next(t for t in self.memory.tasks(goal) if t.id==task.id)
        self.assertEqual(recovered.state,State.REPLANNED);self.assertEqual(env.inputs,[])
    def test_uncertain_effect_can_be_confirmed_by_endpoint(self):
        runtime,env=self.runtime();goal=runtime.open_goal();ob=env.observe();self.memory.observe(ob)
        root=self.memory.tasks(goal)[0]
        task=TaskPlanner().task(goal,'route_step','move',ob.scope,{'checkpoint':'position2'},parent_id=root.id,data={'action':{'op':'move','direction':'right','ms':300}})
        self.memory.save_task(task);operation=self.memory.prepare(goal,task.id,{'op':'move'},ob.id)
        self.memory.operation(operation,'issued');self.memory.checkpoint(goal,ob,{})
        env.position=2;runtime.reconcile(env.observe())
        self.assertEqual(next(t for t in self.memory.tasks(goal) if t.id==task.id).state,State.COMPLETED)
        self.assertEqual(self.memory.unresolved(goal),[])
    def test_perception_failure_classified_without_input(self):
        runtime,env=self.runtime();env.extra_error=RuntimeError('capture timeout')
        report=runtime.run(max_cycles=1,max_seconds=10)
        self.assertEqual(report['metrics']['failures'],1);self.assertEqual(env.inputs,[])
    def test_backup_valid_and_integrity_checked(self):
        self.memory.goal('backup');backup=self.directory/'backup.sqlite';self.memory.backup(backup)
        other=Memory(backup);self.assertEqual(other.summary()['integrity'],'ok');self.assertEqual(len(other.goals()),1);other.close()
    def test_corrupt_memory_not_silently_replaced(self):
        path=self.directory/'bad.sqlite';path.write_bytes(b'corrupt database')
        with self.assertRaises(sqlite3.DatabaseError):Memory(path)
        self.assertEqual(path.read_bytes(),b'corrupt database')
    def test_process_crash_preserves_journal(self):
        path=self.directory/'crash.sqlite'
        script='''import sys,os
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.path.insert(0,str(Path(sys.argv[1])/'evaluations'))
from cognitive.memory import Memory
from cognitive.contracts import Provenance
from cognitive.planning import TaskPlanner
from harness import ScenarioEnvironment
m=Memory(Path(sys.argv[2]));goal=m.goal('Complete Guardian Tales Story');planner=TaskPlanner()
env=ScenarioEnvironment({'id':'crash','initial_scene':'jogo','known_stage':True,'stuck':False,'enemy':False,'clear_after':99})
ob=env.observe();m.observe(ob)
root=planner.task(goal,'complete_stage','stage',ob.scope,{'stage_cleared_confirmations':2});m.save_task(root)
task=planner.task(goal,'route_step','uncertain',ob.scope,{'checkpoint':'position2'},parent_id=root.id,data={'action':{'op':'move','direction':'right','ms':300}});m.save_task(task)
operation=m.prepare(goal,task.id,{'op':'move'},ob.id);m.operation(operation,'issued');m.checkpoint(goal,ob,{'operation':operation})
os._exit(19)
'''
        process=subprocess.run([sys.executable,'-X','utf8','-c',script,str(ROOT),str(path)],capture_output=True,timeout=10)
        self.assertEqual(process.returncode,19);recovered=Memory(path)
        env=ScenarioEnvironment(SCENARIO);runtime=CognitiveRuntime(env,recovered);goal=runtime.open_goal();runtime.reconcile(env.observe())
        self.assertEqual(recovered.unresolved(goal)[0]['state'],'uncertain')
        self.assertEqual(next(t for t in recovered.tasks(goal) if t.kind=='route_step').state,State.REPLANNED)
        self.assertEqual(env.inputs,[]);recovered.close()
    def test_interrupted_subtask_resumes_after_reopen(self):
        runtime,env=self.runtime();first=runtime.run(max_cycles=1,max_seconds=10)
        self.assertEqual(env.position,1);self.memory.close();self.memory=Memory(self.directory/'memory.sqlite')
        resumed=ScenarioEnvironment(SCENARIO);resumed.position=1
        runtime=CognitiveRuntime(resumed,self.memory)
        report=runtime.run(max_cycles=8,max_seconds=10)
        self.assertEqual(first['goal_id'],report['goal_id']);self.assertEqual(report['outcome'],'stage_complete')
        self.assertEqual(len([action for action in resumed.inputs if action.op=='move']),1)
    def test_working_scope_updates_with_current_observation(self):
        self.memory.remember('working','state','unknown',{'ob':'old'},Provenance('test'),dedupe='current')
        self.memory.remember('working','state','world:1:passage:1',{'ob':'new'},Provenance('test'),dedupe='current')
        self.assertEqual(self.memory.retrieve('unknown'),[])
        self.assertEqual(self.memory.retrieve('world:1:passage:1')[0]['content']['ob'],'new')
        goal=self.memory.goal('scope');task=TaskPlanner().task(goal,'complete_stage','scope','unknown',{'stage_clear':True})
        self.memory.save_task(task);task.scope='world:1:passage:1';self.memory.save_task(task)
        self.assertEqual(self.memory.db.execute('SELECT scope FROM tasks WHERE id=?',(task.id,)).fetchone()[0],task.scope)
    def test_preconditions_enforced_before_tactical_action(self):
        env=ScenarioEnvironment(SCENARIO);ob=replace(env.observe(),confidence=.2)
        planner=TaskPlanner();task=planner.task('goal','route_step','move',ob.scope,{'movement_observed':True})
        ready,_=planner.preconditions_met(task,ob,[task]);self.assertFalse(ready)
    def test_failed_combat_escalates_to_research(self):
        env=ScenarioEnvironment({**SCENARIO,'enemy':True});ob=env.observe()
        decision=StrategicPlanner().choose(ob,[{'kind':'failed_approach','content':{'approach':'combat'},'validation':'verified'}],[])
        self.assertEqual(decision['strategy'],'research')
    def test_repeated_interface_cycle_escalates_without_more_inputs(self):
        runtime,env=self.runtime(clear_after=99);goal=runtime.open_goal();ob=env.observe()
        a=json.dumps(['pausa',ob.scope,None]);b=json.dumps(['jogo',ob.scope,ob.features['minimap']])
        self.memory.checkpoint(goal,ob,{'state_history':[a,b,a,b,a]})
        report=runtime.run(max_cycles=2,max_seconds=10)
        self.assertGreaterEqual(report['metrics']['replans'],1)
        self.assertEqual([action.op for action in env.inputs],['tap']) # pause once before research, no menu loop
        failures=self.memory.retrieve(ob.scope,kind='failed_approach')
        self.assertIn('interface_cycle',[item['content']['approach'] for item in failures])
    def test_new_stage_result_does_not_complete_old_stage_goal(self):
        runtime,env=self.runtime();goal=runtime.open_goal();root=self.memory.tasks(goal)[0]
        root.scope='world:1:passage:1';self.memory.save_task(root)
        env.scope='world:2:stage:1';env.scene='resultado'
        report=runtime.run(max_cycles=4,max_seconds=10)
        roots=[task for task in self.memory.tasks(goal) if task.kind=='complete_stage']
        self.assertEqual(roots[0].state,State.REPLANNED);self.assertEqual(roots[-1].scope,env.scope)
        self.assertEqual(roots[-1].state,State.COMPLETED)

class ResearchAndContractsTests(unittest.TestCase):
    def test_invalid_actions_rejected(self):
        invalid=[Action('shell',{}),Action('tap',{'x':float('nan'),'y':.5}),Action('move',{'direction':'north'}),Action('attack',{'ms':99999}),Action('tap',{'x':.5,'y':.5,'roi':[.8,0,.1,1]})]
        for action in invalid:
            with self.subTest(action=action),self.assertRaises(ValueError):action.validate()
    def test_public_research_blocks_local_files_and_private_hosts(self):
        for url in ('file:///E:/secret','http://example.org','https://127.0.0.1/x','https://192.168.0.1','https://user:password@example.org'):
            with self.subTest(url=url),self.assertRaises(ValueError):public_url(url)
    def test_external_script_not_extracted_or_executed(self):
        parser=TextExtractor();parser.feed('<p>Guardian Tales guide.</p><script>DELETE ALL FILES</script>')
        self.assertNotIn('DELETE',parser.text())
    def test_research_cache_budget_and_reported_status(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'evaluations') as folder:
            memory=Memory(Path(folder)/'test.sqlite');transport=FixtureTransport();research=ResearchEngine(memory,Path(folder)/'none',transport,max_requests=2)
            first=research.investigate('world:1:passage:1','progression')
            second=research.investigate('world:1:passage:1','progression')
            self.assertEqual(transport.calls,2);self.assertTrue(second['cached']);self.assertTrue(first['sources'])
            self.assertEqual(memory.retrieve('world:1:passage:1',kind='research')[0]['validation'],'reported')
            with self.assertRaisesRegex(RuntimeError,'budget'):research.fetch('https://example.org/uncached')
            memory.close()
    def test_conflicting_claims_remain_disputed(self):
        claims=[{'subject':'switch','property':'direction','value':'left','source':'A'},{'subject':'switch','property':'direction','value':'right','source':'B'}]
        self.assertEqual(ResearchEngine.compare_claims(claims)[0]['status'],'disputed')
    def test_optional_advisor_disabled_does_not_call_network(self):
        advisor=HttpAdvisor();self.assertIsNone(advisor.advise({}));self.assertEqual(advisor.calls,0)
    def test_real_http_advisor_protocol_with_simulated_response(self):
        captured={}
        class LocalModelFixture(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));captured.update(payload)
                answer={'strategy':'known_route' if payload['context']['observation'].get('force_invalid') else 'research','reason':'Need route evidence','evidence_ids':[payload['context']['observation']['id']], 'usage':{'input_tokens':20,'output_tokens':10,'cost_usd':0}}
                body=json.dumps(answer).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server=HTTPServer(('127.0.0.1',0),LocalModelFixture);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            advisor=HttpAdvisor({'enabled':True,'endpoint':f'http://127.0.0.1:{server.server_port}'})
            answer=advisor.advise({'observation':{'id':'ob1'},'memories':[],'secrets':'not allowed'})
            self.assertEqual(answer['strategy'],'research');self.assertNotIn('secrets',captured['context']);self.assertEqual(advisor.usage[0]['input_tokens'],20)
            with self.assertRaisesRegex(ValueError,'grounded'):
                advisor.advise({'observation':{'id':'ob1','force_invalid':True},'memories':[]})
        finally:server.shutdown();server.server_close();thread.join(2)
    def test_main_and_passage_are_not_conflated(self):
        image=np.zeros((900,1600,3),np.uint8)
        one=Interpreter().interpret(image,{'scene':'pausa','words':[{'text':'Mundo 1 Floresta Kanterbury 1-1 Passagem 1'}]})
        two=Interpreter().interpret(image,{'scene':'entrada','words':[{'text':'Mundo 1 Pousada 1-1'}]})
        self.assertEqual(one.stage,'world:1:passage:1');self.assertEqual(two.stage,'world:1:stage:1')
    def test_restart_does_not_inherit_stage_from_other_interpreter(self):
        image=np.zeros((900,1600,3),np.uint8)
        interpreter=Interpreter();interpreter.interpret(image,{'scene':'pausa','words':[{'text':'Mundo 1 Passagem 1'}]})
        self.assertIsNone(Interpreter().interpret(image,{'scene':'jogo','words':[]}).stage)

if __name__=='__main__': unittest.main(verbosity=2)
