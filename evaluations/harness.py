"""Deterministic action-conditioned simulator, explicitly NOT live gameplay."""
from __future__ import annotations
from pathlib import Path
import json, statistics, sys, tempfile, threading, time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cognitive.contracts import Action, Observation, Provenance, now, uid
from cognitive.memory import Memory
from cognitive.runtime import CognitiveRuntime

class ScenarioEnvironment:
    def __init__(self,scenario):
        self.scenario=scenario; self.scene=scenario['initial_scene']; self.known=scenario['known_stage']
        self.position=0; self.enemy=scenario['enemy']; self.inputs=[]; self.scope='world:1:passage:1'
        self.extra_error=None
    def observe(self):
        if self.extra_error: error=self.extra_error; self.extra_error=None; raise error
        vector=[self.position*3]*384
        stage=self.scope if self.known or self.scene in ('pausa','resultado') else None
        return Observation(uid('sim_observation'),now(),self.scene,.95,stage or 'unknown',stage,
            'simulated stage label' if self.known else '',
            {'stage_observed':self.scene in ('pausa','resultado'),'stage_confidence':.95 if stage else 0,'enemy_count':int(self.enemy),'enemy':[.5,.48] if self.enemy else None,
             'health':1.0,'visual_vector':vector,'visual_hash':str((self.scene,self.position,self.enemy)),
             'minimap':str(self.position),'stage_cleared':self.scene=='resultado'},blocked='reviver' if self.scene=='bloqueada' else None,
             provenance=Provenance('simulation:'+self.scenario['id'],method='action_conditioned_fixture'))
    def execute(self,action):
        action.validate(); self.inputs.append(action)
        if action.op=='tap': self.scene='pausa'; self.known=True
        elif action.op=='text': self.scene='jogo'
        elif action.op=='attack': self.enemy=False
        elif action.op=='move' and not self.scenario['stuck']:
            self.position+=1
            if self.position>=self.scenario['clear_after']: self.scene='resultado'; self.known=True
    def route_candidates(self,ob):
        if self.scene!='jogo' or self.position!=0 or self.enemy: return []
        return [{'id':'simulated_route','scope':self.scope,'score':1,'end_anchor':'position2','steps':[
            {'op':'move','direction':'right','ms':300}, {'op':'move','direction':'right','ms':300}]}]
    def checkpoint_matches(self,ob,anchor,threshold=.91): return anchor=='position2' and self.position==2

class FixtureTransport:
    """Synthetic research for offline tests only; never reported as web research."""
    def __init__(self): self.calls=0
    def fetch(self,url,timeout=8):
        self.calls+=1
        if 'format=rss' in url: return '<rss><channel><item><title>Guardian Tales test guide</title><link>https://example.org/guardian-guide</link><description>Guardian Tales passage route</description></item></channel></rss>'
        return '<html><body><p>Guardian Tales passage progression: inspect the map and verify the next checkpoint before moving. This is a synthetic fixture, not a real game guide.</p></body></html>'

def baseline(scenario):
    """Explicit naive monolithic baseline: reactive commands, no task or memory."""
    env=ScenarioEnvironment(scenario); started=time.perf_counter(); decisions=[]
    for _ in range(scenario['cycles']):
        ob=env.observe()
        if ob.blocked: break
        if ob.scene=='resultado': break
        if ob.stage is None: action=Action('tap',{'x':.106,'y':.13})
        elif ob.scene=='pausa': action=Action('text',{'text':'Continuar'})
        elif ob.features['enemy_count']: action=Action('attack',{'ms':600})
        else: action=Action('move',{'direction':'right','ms':300})
        stamp=time.perf_counter();env.execute(action);decisions.append((time.perf_counter()-stamp)*1000)
    return {'variant':'A_monolithic_no_memory','scenario':scenario['id'],'simulated':True,'stage_clear':env.scene=='resultado','actions':len(env.inputs),
        'unnecessary_actions':max(0,len([a for a in env.inputs if a.op=='move'])-1) if scenario['stuck'] else 0,
        'latency_ms':round((time.perf_counter()-started)*1000,3),'decision_median_ms':statistics.median(decisions) if decisions else 0,
        'tokens':0,'cost_usd':0,'note':'Handwritten naive baseline, not a universal agent comparison.'}

def hierarchical(scenario,directory):
    from cognitive.research import ResearchEngine
    env=ScenarioEnvironment(scenario); memory=Memory(directory/'memory.sqlite'); transport=FixtureTransport()
    research=ResearchEngine(memory,directory/'missing_library.json',transport)
    runtime=CognitiveRuntime(env,memory,research,event_path=directory/'events.jsonl')
    started=time.perf_counter(); report=runtime.run(max_cycles=scenario['cycles'],max_seconds=60)
    tasks=memory.tasks(report['goal_id']); verified_stage=any(t.kind=='complete_stage' and t.state=='completed' for t in tasks)
    data={'variant':'B_hierarchical_persistent','scenario':scenario['id'],'simulated':True,'stage_clear':verified_stage,
        'actions':report['metrics']['actions'],'unnecessary_actions':max(0,len([a for a in env.inputs if a.op=='move'])-1) if scenario['stuck'] else 0,
        'latency_ms':round((time.perf_counter()-started)*1000,3),'decision_median_ms':statistics.median(report['metrics']['decision_ms']) if report['metrics']['decision_ms'] else 0,
        'tokens':0,'cost_usd':0,'outcome':report['outcome'],'replans':report['metrics']['replans'],'fixture_research_requests':transport.calls,
        'task_completion_rate':sum(task.state=='completed' for task in tasks)/len(tasks) if tasks else None,
        'task_counts':{state:sum(task.state==state for task in tasks) for state in ('completed','failed','replanned','blocked')}}
    memory.close(); return data

def main():
    scenarios=json.loads((ROOT/'evaluations/scenarios.json').read_text())
    report={'environment':'action-conditioned simulation; no game commands or paid model calls','scenarios':scenarios,'results':[]}
    for scenario in scenarios:
        with tempfile.TemporaryDirectory(dir=ROOT/'evaluations') as folder:
            report['results'].extend([baseline(scenario),hierarchical(scenario,Path(folder))])
    report['limits']=['Small deterministic scenarios do not establish real-game success rates.','The monolithic baseline is an explicit simple reactive policy.','Latency is local CPU/database time; network and OCR absent.','Zero tokens/cost refers to these no-model runs; unconfigured provider cost is unknown.']
    (ROOT/'evaluations/benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
