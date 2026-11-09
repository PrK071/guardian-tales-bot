"""Short observed calibration. Always pause before returning to human analysis."""
from pathlib import Path
import argparse,json,urllib.request
from bot import ADB
from cognitive.contracts import Action
from cognitive.fast_control import FastSession
from cognitive.memory import Memory
ROOT=Path(__file__).resolve().parent
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('op',choices=['move','attack','interact','observe','fight','navigate']);parser.add_argument('direction',nargs='?',default='up');parser.add_argument('--ms',type=int,default=400);parser.add_argument('--steps',type=int,default=1);args=parser.parse_args()
    try:urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=1)
    except Exception:pass
    else:raise SystemExit('Run calibration only while the main server is explicitly stopped, or through its future V2 job.')
    memory=Memory(ROOT/'data/cognitive.sqlite');session=FastSession(ROOT,ADB(),memory)
    try:
        session.capture('initial')
        if args.op=='navigate':
            for _ in range(min(12,args.steps)):print(json.dumps(session.navigate_once()),flush=True)
        else:session.transition('jogo')
        if args.op=='fight':print(json.dumps(session.fight()),flush=True)
        elif args.op not in ('observe','navigate'):session.pulse(Action(args.op,{'direction':args.direction,'ms':args.ms} if args.op=='move' else {'ms':args.ms}))
    finally:
        try:session.transition('pausa')
        finally:
            report=session.close();memory.close();print(json.dumps({'folder':str(session.folder),'actions':len(report['actions']),'seconds':report['seconds']}))
