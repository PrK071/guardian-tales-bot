from pathlib import Path
import hashlib,json,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import cv2
from rapidocr_onnxruntime import RapidOCR
from cognitive.perception import Interpreter
from bot import Bot

class CaptureFixture:
    def __init__(self,frame):self.frame=frame
    def foreground(self):return True
    def capture(self):return self.frame

def main():
    cases=[('captures/initial.png','mapa',None),('captures/adb-enabled.png','entrada','world:1:passage:1'),
           ('captures/1794088457275347900-before.png','jogo',None)]
    controller=Bot();controller.ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
    results=[]
    for path,scene,stage in cases:
        frame=cv2.imread(str(ROOT/path));controller.adb=CaptureFixture(frame);start=time.perf_counter()
        image,snapshot=controller.observe();ob=Interpreter().interpret(image,snapshot)
        results.append({'file':path,'sha256':hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),'expected_scene':scene,'observed_scene':ob.scene,
                        'expected_stage':stage,'observed_stage':ob.stage,'correct':ob.scene==scene and ob.stage==stage,'latency_ms':round((time.perf_counter()-start)*1000,2)})
    report={'input':'historical real screenshots; offline OCR/CV replay, no live game commands','cases':results,
            'scene_accuracy':sum(r['correct'] for r in results)/len(results),'limits':'Three screenshots only; does not establish general perception accuracy.'}
    (ROOT/'evaluations/perception-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not all(r['correct'] for r in results):raise SystemExit(1)
if __name__=='__main__':main()
