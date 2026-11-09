from pathlib import Path
import json,sys,threading,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from cognitive.local_model import LocalLlamaAdvisor
if __name__=='__main__':
    advisor=LocalLlamaAdvisor(ROOT,{'enabled':True});advisor.cancel=threading.Event();advisor.cancel.set();started=time.perf_counter()
    try:
        advisor.advise({'observation':{'id':'cancel_eval','scene':'jogo','stage':'world:1:passage:1','features':{}},'memories':[]})
        report={'cancelled':False}
    except InterruptedError:
        report={'cancelled':True,'process':advisor.last_cancelled,'elapsed_ms':round((time.perf_counter()-started)*1000,2),'live_game_input':False}
    (ROOT/'evaluations/model-cancel.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    if not report['cancelled'] or report['process']['returncode'] is None:raise SystemExit(1)
