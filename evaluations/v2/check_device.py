"""Bounded read-only preflight. Does not restart or control the game."""
from pathlib import Path
import json,subprocess,time
ROOT=Path(__file__).resolve().parents[2];config=json.loads((ROOT/'config.json').read_text())
rows=[]
for args in (['get-state'],['shell','echo','v2_ping'],['exec-out','screencap']):
    start=time.perf_counter()
    try:
        result=subprocess.run([str(ROOT/config['adb']),'-s',config['serial'],*args],capture_output=True,timeout=4,creationflags=0x08000000)
        row={'command':args,'exit':result.returncode,'stdout_bytes':len(result.stdout),'stderr':result.stderr.decode(errors='replace')[:300],'ms':round((time.perf_counter()-start)*1000,2)}
        row['ok']=result.returncode==0 and bool(result.stdout)
    except subprocess.TimeoutExpired:row={'command':args,'ok':False,'error':'timeout','ms':round((time.perf_counter()-start)*1000,2)}
    rows.append(row)
    if not row['ok']:break
report={'at':time.time(),'ok':len(rows)==3 and all(r['ok'] for r in rows),'probes':rows,'previous_observed_failures':['dumpsys activity timed out after 15s','shell echo and raw screencap timed out after 5s','disconnect/connect failed','ADB server restart completed; reconnect still failed'],'game_input_sent':False}
(ROOT/'evaluations/v2/device-status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
