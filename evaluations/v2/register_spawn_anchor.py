"""Derive a map reference from a closed, verified initial-stage observation."""
from pathlib import Path
import json,sys
import cv2
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from cognitive.map_navigation import PauseMap
from cognitive.map_anchor import SpawnMapAnchor
from cognitive.memory import Memory
from cognitive.contracts import Provenance
folder=(ROOT/'data/v2/v2_trial_5aa90fc7327340cf').resolve()
report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
if not report.get('initial_spawn_verified') or report.get('scope')!='world:1:passage:1' or report.get('kind')!='initial_stage_trial':raise RuntimeError('Source is not a verified initial-stage trial')
source=folder/'0000-initial.jpg';state=PauseMap().parse(cv2.imread(str(source)));anchor=SpawnMapAnchor.from_map(state)
data=anchor.save(folder/'spawn-map-anchor-derived.png');data['source_frame']=str(source);data['source_report']=str(folder/'report.json');data['derived_after_trial']=True
memory=Memory(ROOT/'data/cognitive.sqlite')
try:mid=memory.remember('semantic','v2_spawn_anchor',report['scope'],data,Provenance(str(source),method='derived_from_verified_initial_trial'),.95,'verified',dedupe='v2:spawn-anchor:'+report['scope'])
finally:memory.close()
(folder/'anchor-registration.json').write_text(json.dumps({'memory_id':mid,**data},indent=2),encoding='utf-8');print(json.dumps({'memory_id':mid,**data}))
