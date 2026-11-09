"""Read-only operation/journal measurement; no physical-collision inference."""
from pathlib import Path
import argparse,json,sqlite3
ROOT=Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runs',nargs='+',required=True);args=parser.parse_args()
    db=sqlite3.connect((ROOT/'data/cognitive.sqlite').as_uri()+'?mode=ro',uri=True)
    stalls=[json.loads(row[0]) for row in db.execute("SELECT content FROM memories WHERE kind='v3_exit_stall' AND validation='verified'")]
    cases=[]
    try:
        for name in args.runs:
            folder=(ROOT/'data/v3'/name).resolve()
            if folder.parent!=(ROOT/'data/v3').resolve():raise ValueError('Run outside trial data')
            trial=json.loads((folder/'report.json').read_text());controls=[]
            for control in trial.get('continuous_actions',[]):
                row=db.execute('SELECT action FROM operations WHERE id=?',(control.get('operation_id'),)).fetchone()
                if not row or json.loads(row[0]).get('op')!='final_corridor_exit_forward':continue
                controls.append({k:control.get(k) for k in ('operation_id','kind','direction','requested_ms','actual_ms','outcome')})
            selected=[s for s in stalls if s.get('run_id')==name];ids={s['control']['operation_id'] for s in selected};known={c['operation_id'] for c in controls}
            if not ids.issubset(known):raise ValueError('A confirmed stall lacks a matching issued exit operation')
            cases.append({'run_id':name,'entry_token':trial['active_plan'].get('entry_token'),'source_report':str((folder/'report.json').relative_to(ROOT)),'exit_move_holds':len(controls),'map_confirmed_stalled_holds':len(ids),'detected_stall_fraction':len(ids)/len(controls) if controls else None,'confirmed_stage_exit':trial.get('outcome')=='stage_complete','controls':controls,'stalls':selected})
    finally:db.close()
    result={'scope':'Detected map-confirmed nonprogress during issued final-corridor exit holds; not physical collision rate','comparison_limit':'Trials can begin at different positions, including after a calibrated lateral correction. This is not an equivalent V2/V3 collision or speed benchmark. Repeated stalled holds at the same wall are separate attempts, not separate physical episodes.','physical_collision_rate':None,'cases':cases}
    path=ROOT/'evaluations/v3/exit-stall-metrics.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:c[k] for k in ('run_id','exit_move_holds','map_confirmed_stalled_holds','detected_stall_fraction')} for c in cases]))

if __name__=='__main__':main()
