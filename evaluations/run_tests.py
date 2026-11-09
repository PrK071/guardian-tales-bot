from pathlib import Path
import json,sys,time,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
if __name__=='__main__':
    started=time.perf_counter()
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_bot','test_cognitive'])
    with (ROOT/'logs/unit-tests.txt').open('w',encoding='utf-8') as output:
        result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
    report={'tests_run':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
            'failures':[{'test':str(t),'traceback':message} for t,message in result.failures],
            'errors':[{'test':str(t),'traceback':message} for t,message in result.errors],
            'skipped':[str(t) for t,_ in result.skipped],'duration_ms':round((time.perf_counter()-started)*1000,2),
            'scope':'Legacy guards + cognitive contracts/memory/planning/recovery/research; simulator/model response fixtures are explicitly synthetic.'}
    (ROOT/'evaluations/unit-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
