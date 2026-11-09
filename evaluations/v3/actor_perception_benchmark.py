"""Paired replay of actor-refinement optimization; no gameplay inputs."""
from pathlib import Path
import hashlib,importlib.util,json,math,statistics,sys,time
import cv2
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from cognitive.spatial import SpatialVision
path=ROOT/'backups/v3-spatial-before-actor-optimization.py';spec=importlib.util.spec_from_file_location('v3_old_spatial',path);old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
files=[ROOT/'data/v3/v3_lantern_probe_1c712db0ca8c40f8/0002-v3-glove-preflight.jpg',ROOT/'data/v3/v3_lantern_probe_1c712db0ca8c40f8/0005-v3-glove-removal-check.jpg',ROOT/'data/v3/v3_lantern_probe_c7253326189c4557/0005-v3-glove-removal-check.jpg',ROOT/'data/v3/v3_lantern_probe_215c1f24d894442e/0030-v3-fixed-independent-check.jpg']
frames=[cv2.imread(str(p)) for p in files];rows=[]
for held in (False,True):
 for repetition in range(3):
  for file,frame in zip(files,frames):
   pair={}
   for name,cls in ([('before',old.SpatialVision),('after',SpatialVision)] if repetition%2==0 else [('after',SpatialVision),('before',old.SpatialVision)]):
    vision=cls();vision.skip_helmet_templates=held;began=time.perf_counter();features=vision.entities(frame);pair[name]={'ms':(time.perf_counter()-began)*1000,'raw_player':features['player'],'combat_present':features['combat_present']}
   rows.append({'held_pipeline':held,'frame':str(file.relative_to(ROOT)),'repetition':repetition,**pair})
def stats(values):
 values=sorted(values);return {'n':len(values),'mean':statistics.mean(values),'p95':values[math.ceil(.95*len(values))-1]}
result={'scope':'paired offline replay, actor perception only; excludes carried-pose matcher, capture and input','source_sha256':{'before':hashlib.sha256(path.read_bytes()).hexdigest(),'after':hashlib.sha256((ROOT/'cognitive/spatial.py').read_bytes()).hexdigest()},'groups':{str(held):{name:stats([r[name]['ms'] for r in rows if r['held_pipeline']==held]) for name in ('before','after')} for held in (False,True)},'rows':rows}
assert all(r['before']['combat_present']==r['after']['combat_present'] for r in rows)
(ROOT/'evaluations/v3/actor-perception-benchmark.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result['groups']))
