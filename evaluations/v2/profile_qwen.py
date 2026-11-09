from pathlib import Path
import json,statistics,sys,time
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from cognitive.contracts import Observation
from cognitive.memory import Memory
from cognitive.runtime import CognitiveRuntime
from cognitive.local_model import LocalLlamaAdvisor

def main():
    initial=json.loads((ROOT/'data/v2/initial-status.json').read_text(encoding='utf-8'))
    ob=Observation.from_dict(initial['cognitive']['current']);memory=Memory(ROOT/'data/cognitive.sqlite')
    runtime=CognitiveRuntime(None,memory);retrieval_start=time.perf_counter();memories=runtime.context(ob);retrieval_ms=(time.perf_counter()-retrieval_start)*1000
    context={'observation':ob.to_dict(),'memories':memories,'tasks':initial['cognitive']['tasks'],'routes':[],'budget':{'remaining_model_calls':1}}
    rows=[]
    for repeat in range(3):
        for mode in ('full_current','minimal','selective'):
            advisor=LocalLlamaAdvisor(ROOT,{'enabled':True,'context_mode':mode,'profile_tokenization':True,'timeout_seconds':90,'threads':2})
            start=time.perf_counter()
            try:
                answer=advisor.advise(context);row={'mode':mode,'repeat':repeat,'answer':answer,'usage':advisor.usage[-1],
                    'grounded_strategy':answer['strategy'] in ('inspect','research','wait','stop'),'source':'real_local_model_no_game_commands'}
            except Exception as error:row={'mode':mode,'repeat':repeat,'error':str(error),'grounded_strategy':False}
            row['wall_ms']=round((time.perf_counter()-start)*1000,3);row['memory_retrieval_ms']=round(retrieval_ms,3);rows.append(row)
            (ROOT/'evaluations/v2/qwen-profile.json').write_text(json.dumps({'complete':False,'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(row,ensure_ascii=False),flush=True)
    summary={}
    for mode in ('full_current','minimal','selective'):
        group=[r for r in rows if r['mode']==mode];latencies=sorted(r['usage']['profile']['inference_process_ms'] for r in group if r.get('usage'))
        summary[mode]={'samples':len(group),'grounded':sum(r['grounded_strategy'] for r in group),'mean_inference_ms':statistics.mean(latencies) if latencies else None,
                       'p95_inference_ms':latencies[-1] if latencies else None,'p95_method':'nearest-rank; n=3, so maximum',
                       'mean_input_tokens':statistics.mean(r['usage']['input_tokens'] for r in group if r.get('usage')) if latencies else None}
    report={'complete':True,'rows':rows,'summary':summary,'hardware':'existing i5-7400; CPU, 2 threads; unchanged Qwen3-0.6B Q8 weights',
            'controls':'same prompt instructions, schema, seed, temperature and 160-token output budget; order interleaved over 3 rounds',
            'limits':['tokenizer probe includes executable/metadata startup','small decision sample, not a puzzle-solving benchmark','selective/minimal context applies to this observed decision; no general quality guarantee'],
            'deterministic_opportunity':'Identified pause screen and an exact Continue target can be handled without LLM. No model replacement proposed.'}
    (ROOT/'evaluations/v2/qwen-profile.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');memory.close()
    print(json.dumps(summary,indent=2),flush=True)
if __name__=='__main__':main()
