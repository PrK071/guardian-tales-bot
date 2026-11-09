"""Recompute measurements from persisted game calibration and model evidence."""
from pathlib import Path
import json,math,statistics,time
ROOT=Path(__file__).resolve().parents[2]
def stats(values):
    values=sorted(values)
    return {'samples':len(values),'mean':round(statistics.mean(values),3) if values else None,'p95':round(values[math.ceil(.95*len(values))-1],3) if values else None,'p95_method':'nearest rank'}
reports=[]
for path in (ROOT/'data/v2').glob('v2_*/report.json'):
    row=json.loads(path.read_text(encoding='utf-8'));reports.append((str(path.relative_to(ROOT)),row))
calibrations=[(p,r) for p,r in reports if r.get('kind')=='calibration_not_autonomous_stage_completion']
lantern_calibrations=[(p,r) for p,r in reports if r.get('kind')=='lantern_calibration_not_stage_completion']
joystick_calibrations=[(p,r) for p,r in reports if r.get('kind')=='joystick_calibration_not_stage_completion']
trials=[(p,r) for p,r in reports if r.get('kind') in ('initial_stage_trial','resumed_stage_trial')]
initial=[r for p,r in trials if r.get('initial_spawn_verified')]
trial_metrics=[r.get('metrics',{}) for _,r in trials]
trial_actions=[a for _,r in trials for a in r.get('actions',[])]
trial_seconds=sum(r['seconds'] for _,r in trials)
trial_mapped=[a['metrics']['map_motion'] for a in trial_actions if a['action']['op']=='move' and 'map_motion' in a['metrics']]
trial_stable=[m for m in trial_mapped if m['same_map_extent']]
trial_aligned=[a['metrics']['aligned_map_motion'] for a in trial_actions if 'aligned_map_motion' in a['metrics']]
device=json.loads((ROOT/'evaluations/v2/device-status.json').read_text(encoding='utf-8'))
conversation_confirmations=0
for line in (ROOT/'logs/cognitive.jsonl').read_text(encoding='utf-8').splitlines():
    event=json.loads(line);data=event.get('data',{})
    if event.get('kind')=='v2_cycle' and data.get('kind')=='interaction' and data.get('result',{}).get('verified'):conversation_confirmations+=1
actions=[a for p,r in calibrations for a in r['actions']];moves=[a for a in actions if a['action']['op']=='move']
mapped=[a['metrics']['map_motion'] for a in moves if 'map_motion' in a['metrics']]
stable=[m for m in mapped if m['same_map_extent']]
repeated=0
for _,run in calibrations:
    previous=None
    for action in run['actions']:
        if action['action']['op']!='move':continue
        motion=action['metrics'].get('map_motion',{})
        failed=motion.get('same_map_extent') and not motion.get('verified')
        if failed and previous and previous['action']['args']['direction']==action['action']['args']['direction']:
            prior=previous['metrics']['map_motion'];repeated+=math.dist(prior['before'],motion['before'])<8
        previous=action if failed else None
seconds=sum(r['seconds'] for _,r in calibrations)
model=json.loads((ROOT/'evaluations/v2/qwen-profile.json').read_text(encoding='utf-8'))
rows=model['rows'];profiles=[r['usage']['profile'] for r in rows if r.get('usage')]
report={'generated_at':time.time(),'calibration_runs':len(calibrations),'calibration_seconds':round(seconds,3),'calibration_actions':len(actions),'move_actions':len(moves),
 'lantern_calibrations':[{'report':p,'phase':r.get('phase'),'seconds':r['seconds'],'actions':len(r['actions']),'result':r.get('result'),'error':r.get('error'),'stage_complete':False} for p,r in lantern_calibrations],
 'joystick_calibrations':[{'report':p,'seconds':r['seconds'],'result':r.get('result'),'error':r.get('error'),'stage_complete':False} for p,r in joystick_calibrations],
 'stage_trials':len(trials),'initial_to_finish_trials':len(initial),'initial_to_finish_completed':sum(r.get('outcome')=='stage_complete' for r in initial),
 'initial_stage_completion_rate':sum(r.get('outcome')=='stage_complete' for r in initial)/len(initial) if initial else None,
 'stage_rate_limit':'Only closed trial reports are counted. Calibration, menu preparation and pre-input ADB failure are separate; unclosed artifacts do not prove a live process or a finished attempt.',
 'trial_results':[{'report':p,'kind':r['kind'],'outcome':r.get('outcome'),'reason':r.get('reason'),'seconds':r['seconds'],'actions':len(r.get('actions',[])),'code_hashes_at_start':r.get('code_hashes_at_start'),'health_first_action':r['actions'][0]['before']['health'] if r.get('actions') else None,'health_last_action':r['actions'][-1]['after']['health'] if r.get('actions') else None} for p,r in trials],
 'controller_ms':stats([a['metrics']['controller_ms'] for a in actions]),'capture_ms':stats([a['after']['capture_ms'] for a in actions]),
 'map_confirmed_moves':sum(m['verified'] for m in stable),'stable_map_unconfirmed_moves':sum(not m['verified'] for m in stable),
 'map_extent_changed_moves':sum(not m['same_map_extent'] for m in mapped),
 'stable_map_progress_pixels':sum(max(0,m['direction_progress']) for m in stable if m['verified']),
 'stable_extent_map_pixels_per_calibration_minute':round(sum(max(0,m['direction_progress']) for m in stable if m['verified'])/(seconds/60),3) if seconds else None,
 'progress_limit':'Local map pixels with stable extent only; not meters, global travel or completion percentage.',
 'movement_flow_confirmed':sum(a['metrics']['motion']['moved'] for a in moves),
 'repeated_unverified_moves':repeated,
 'local_planning_cycles':len([line for p,r in calibrations if (ROOT/p).parent.joinpath('plans.jsonl').exists() for line in (ROOT/p).parent.joinpath('plans.jsonl').read_text(encoding='utf-8').splitlines()]),
 'autonomous_replans_in_stage_trials':sum(m.get('replans',0) for m in trial_metrics),
 'real_puzzle_completions':sum(m.get('puzzle_verified',0) for m in trial_metrics),'real_verified_conversations_v2':conversation_confirmations,
 'failure_incidents':[
  {'kind':'perception','evidence':'v2_calibration_7594db2bc4b1496a','cause':'Large camera motion missed by sparse tracker','correction':'two-flank phase consensus; historical validation'},
  {'kind':'perception','evidence':'v2_calibration_d751883851294319','cause':'Almost-empty enemy HP bar missed','correction':'infer full dark bar; no combat success credited'},
  {'kind':'navigation','evidence':'v2_calibration_3ec3da0ae06d4f1e','cause':'Path followed floor too close to corridor wall','correction':'12-pixel wall clearance; subsequent verified movement'},
  {'kind':'navigation','evidence':'v2_calibration_f2a3ea3b17574c90','cause':'Player pin occluded corridor','correction':'restore icon-occluded rows only between two observed floor sides'},
  {'kind':'tool','evidence':'evaluations/v2/device-status.json','cause':'ADB shell/screencap stopped responding; reconnect failed','correction':'recovered after user restarted MSI' if device['ok'] else 'not recovered yet'},
  {'kind':'navigation','evidence':'v2_trial_76dca5350b004dbb','cause':'Spawn marker sliver selected as zero-length destination; coarse grid aliased eroded corridor','correction':'discard zero-length frontiers; vertical icon reconstruction and four-pixel map grid'},
  {'kind':'perception_and_internal','evidence':'v2_trial_dfcf9912d4a94e9e','cause':'Party HUD mistaken for enemy; kind key conflicted with event signature','correction':'exclude observed portrait region; log nested event data; live-flow regression fixture added'}],
 'model_profile':{'calls':len(rows),'input_tokens':sum(r.get('usage',{}).get('input_tokens',0) or 0 for r in rows),'output_tokens':sum(r.get('usage',{}).get('output_tokens',0) or 0 for r in rows),'by_context':model['summary'],
 'preparation_ms':stats([p['preparation_ms'] for p in profiles]),'retrieval_ms':stats([r['memory_retrieval_ms'] for r in rows]),'wall_ms':stats([r['wall_ms'] for r in rows])},
 'live_stage_metrics':{'closed_trials':len(trials),'seconds':trial_seconds,'actions':len(trial_actions),'navigation_cycle_ms':stats([v for m in trial_metrics for v in m.get('cycle_ms',m.get('decision_ms',[]))]),'isolated_local_planning_ms':stats([v for m in trial_metrics if m.get('timing_scope')=='isolated_local_planning_ms' for v in m.get('decision_ms',[])]),'timing_scope':'Legacy decision_ms includes the full cycle. New reports separate cycle_ms from isolated local decision_ms; never mix the two.',
 'time_per_task_ms':stats([r['seconds']*1000 for _,r in trials]),'model_calls':sum(m.get('model_calls',0) for m in trial_metrics),'input_tokens':sum(m.get('input_tokens',0) for m in trial_metrics),'output_tokens':sum(m.get('output_tokens',0) for m in trial_metrics),
 'recorded_perception_failures':sum(m.get('perception_failures',0) for m in trial_metrics),'recorded_navigation_failures':sum(m.get('navigation_failures',0) for m in trial_metrics),'recorded_verification_failures':sum(m.get('verification_failures',0) for m in trial_metrics),'successful_recoveries':sum(m.get('recoveries',0) for m in trial_metrics),'interruptions_without_recovery':sum(r.get('outcome') in ('blocked','interrupted') for _,r in trials),
 'controller_ms':stats([a['metrics']['controller_ms'] for a in trial_actions]),'map_confirmed_moves':sum(m['verified'] for m in trial_stable),'stable_map_unconfirmed_moves':sum(not m['verified'] for m in trial_stable),'map_extent_changed_moves':sum(not m['same_map_extent'] for m in trial_mapped),'stable_map_progress_pixels_per_minute':sum(max(0,m['direction_progress']) for m in trial_stable if m['verified'])/(trial_seconds/60) if trial_seconds else None,
 'aligned_map_confirmed_moves':sum(m['verified'] for m in trial_aligned),'aligned_map_reference_pixels_per_minute':sum(max(0,m.get('direction_progress',0)) for m in trial_aligned if m['verified'])/(trial_seconds/60) if trial_seconds else None,
 'reason':'Closed actual stage trials only. Recorded counters may omit uncategorized internal failures; each trial preserves its outcome and reason.'},
 'artifact_reports':[p for p,r in reports]}
(ROOT/'evaluations/v2/metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:report[k] for k in ('calibration_runs','calibration_seconds','calibration_actions','move_actions','map_confirmed_moves','controller_ms','stage_trials','initial_stage_completion_rate')},ensure_ascii=False))
