from pathlib import Path
import hashlib,json,sqlite3,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from cognitive.memory import Memory
def load(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
if __name__=='__main__':
    unit=load('evaluations/unit-report.json');perception=load('evaluations/perception-report.json');research=load('evaluations/live-research.json')
    resume=load('evaluations/live-resume.json');model=load('evaluations/real-model.json');cancel=load('evaluations/model-cancel.json');live_model=load('evaluations/live-model-cycle.json')
    final_live=load('evaluations/final-live-cycle.json')
    memory=Memory(ROOT/'data/cognitive.sqlite');summary=memory.summary();memory.backup(ROOT/'data/cognitive-backup.sqlite');memory.close()
    checks={'unit_tests':unit['tests_run']==45 and not unit['failures'] and not unit['errors'],
            'historical_image_replay':perception['scene_accuracy']==1,
            'real_http_research':bool(research['result']['sources']) and research['second_call_cached'],
            'real_process_resume':resume['goal_id_preserved'] and resume['old_tasks_preserved'] and resume['new_run_metrics']['researches']==0,
            'real_model':model['passed'] and model['real_model'],
            'real_model_integrated':live_model['cognitive']['metrics']['model_calls']>=1 and live_model['cognitive']['metrics']['actions']==1,
            'final_live_safe_stop':final_live['game_paused'] and final_live['cognitive']['metrics']['actions']==2 and final_live['cognitive']['metrics']['model_calls']==1,
            'model_cancellation':cancel['cancelled'] and cancel['process']['returncode'] is not None,
            'database_integrity':summary['integrity']=='ok'}
    files=[p for p in (ROOT/'cognitive').glob('*.py')]+[ROOT/'bot.py',ROOT/'config.json',ROOT/'panel.html']
    report={'recorded_at':time.time(),'checks':checks,'evidence_scope':'Acceptance evidence for the architecture base only; not proof of whole-story gameplay.',
            'database':summary,'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            'documentation':['docs/AUDITORIA-ARQUITETURAL.md','docs/ARQUITETURA-COGNITIVA.md','docs/ACEITACAO.md'],
            'remaining_game_capabilities':['Universal puzzles','All-world routes','Validated trap dodge','Boss tactics','VLM/video understanding']}
    (ROOT/'evaluations/acceptance-evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(checks,indent=2))
    if not all(checks.values()):raise SystemExit(1)
