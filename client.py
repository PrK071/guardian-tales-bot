"""Cliente de diagnóstico do painel local (não envia dados à Internet)."""
import json, re, sys, time, urllib.request
from pathlib import Path
BASE='http://127.0.0.1:8765'
ROOT=Path(__file__).resolve().parent
def get(path): return urllib.request.urlopen(BASE+path,timeout=20).read()
def command(job,endpoint='/command'):
    html=get('/').decode('utf-8'); token=re.search("const TOKEN='([^']+)'",html)[1]
    req=urllib.request.Request(BASE+endpoint,json.dumps(job).encode(),headers={'Content-Type':'application/json','X-Bot-Token':token})
    urllib.request.urlopen(req,timeout=20).read()
    if endpoint=='/shutdown':
        print('Servidor encerrado.'); return
    time.sleep(.5)
    end=time.monotonic()+max(120,float(job.get('max_seconds',0))+30)
    while time.monotonic()<end:
        status=json.loads(get('/status'))
        if not status['busy'] and not status.get('pending',0): break
        time.sleep(.5)
    (ROOT/'captures/panel-frame.jpg').write_bytes(get('/frame.jpg'))
    print(json.dumps({'mode':status['mode'],'note':status['note'],'scene':status['snapshot'].get('scene')},ensure_ascii=False))
    if status['mode']=='Revisar': raise SystemExit(1)
if __name__=='__main__':
    args=sys.argv[1:]; kind=args[0]
    if kind=='move': command({'type':'action','action':{'op':'move','direction':args[1],'ms':int(args[2])}})
    elif kind in ('attack','interact','skill'): command({'type':'action','action':{'op':kind,'ms':int(args[1]) if len(args)>1 else 600}})
    elif kind=='tap': command({'type':'action','action':{'op':'tap','x':float(args[1]),'y':float(args[2])}})
    elif kind=='record': command({'type':'record','name':args[1]})
    elif kind=='route': command({'type':'route','name':args[1]})
    elif kind=='cognitive': command({'type':'cognitive','max_cycles':int(args[1]) if len(args)>1 else 8,'max_seconds':180})
    elif kind=='stage_v2': command({'type':'stage_v2','max_steps':int(args[1]) if len(args)>1 else 100,'max_seconds':int(args[2]) if len(args)>2 else 900})
    elif kind=='stage_v3': command({'type':'stage_v3','max_steps':int(args[1]) if len(args)>1 else 100,'max_seconds':int(args[2]) if len(args)>2 else 900})
    elif kind=='shutdown': command({},'/shutdown')
    else: command({'type':kind})
