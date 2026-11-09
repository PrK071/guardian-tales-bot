"""Read-only stream timing/geometry comparison; never sends game input."""
from pathlib import Path
import json,sys,time,statistics
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from bot import ADB
from cognitive.contracts import uid
from cognitive.memory import Memory
from cognitive.v3.session import GameplaySession
from cognitive.map_navigation import PauseMap

memory=Memory(ROOT/'data/cognitive.sqlite');s=GameplaySession(ROOT,ADB(),memory,run_id=uid('v3_video_probe'),video=True)
s.kind='read_only_video_calibration';rows=[];error=None
try:
    for i in range(30):
        start=time.perf_counter();frame,f=s.capture_live('passive-video');row={'wall_ms':(time.perf_counter()-start)*1000,'sample':f['video_sample'],'frame':f['frame'],'scene':f['scene']}
        if f['scene']=='pausa':row['player']=PauseMap().parse(frame)['player']
        rows.append(row);time.sleep(.08)
    _,raw=s.capture('raw-checkpoint');raw_map=PauseMap().parse(s.last_frame) if raw['scene']=='pausa' else None
except Exception as exc:error=type(exc).__name__+': '+str(exc)
finally:
    report=s.close();report.update(error=error,samples=rows,game_input_sent=False)
    if rows:
        report['mean_live_processing_ms']=statistics.mean(r['wall_ms'] for r in rows)
        report['mean_video_interval_ms']=statistics.mean((b['sample']['received_monotonic']-a['sample']['received_monotonic'])*1000 for a,b in zip(rows,rows[1:]))
    (s.folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');memory.close()
    print(json.dumps({'folder':str(s.folder),'error':error,'frames':len(rows),'mean_processing_ms':report.get('mean_live_processing_ms'),'mean_interval_ms':report.get('mean_video_interval_ms'),'input_sent':bool(report['backend']['events'])}),flush=True)
