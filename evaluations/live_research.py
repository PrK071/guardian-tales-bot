from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from cognitive.memory import Memory
from cognitive.research import ResearchEngine
if __name__=='__main__':
    memory=Memory(ROOT/'evaluations/live-research.sqlite')
    research=ResearchEngine(memory,ROOT/'knowledge/worlds.json',max_requests=5)
    first=research.investigate('world:1:passage:1','progression obstacles route')
    second=research.investigate('world:1:passage:1','progression obstacles route')
    report={'real_network':True,'result':first,'second_call_cached':second['cached'],'requests_after_two_calls':research.requests,
            'integrity':memory.summary()['integrity'],'assertion':'Source text is reported knowledge; no gameplay strategy has been validated by this test.'}
    (ROOT/'evaluations/live-research.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2));memory.close()
    if not first['sources'] or not second['cached']:raise SystemExit(1)
