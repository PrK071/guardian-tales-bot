from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from cognitive.local_model import LocalLlamaAdvisor
if __name__=='__main__':
    advisor=LocalLlamaAdvisor(ROOT,{'enabled':True,'timeout_seconds':60})
    context={'observation':{'id':'real_model_eval_1','scene':'jogo','stage':'world:1:passage:1','confidence':.95,'text':'Current stage identified; no known safe continuation.','features':{'enemy_count':0,'health':1.0}},
             'memories':[],'tasks':[],'budget':{'remaining_model_calls':1}}
    answer=advisor.advise(context)
    report={'real_model':True,'live_game_input':False,'context':context,'answer':answer,'usage':advisor.usage,
            'passed':answer['strategy'] in ('research','inspect','stop'),'limits':'One strategic text case. No VLM, puzzle-solving, or general model quality claim.'}
    (ROOT/'evaluations/real-model.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['passed']:raise SystemExit(1)
