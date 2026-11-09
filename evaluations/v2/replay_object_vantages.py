"""Recover relevant object sightings from actual before-action/map image pairs."""
from pathlib import Path
import json,sys,hashlib
import cv2
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from cognitive.contracts import Provenance
from cognitive.memory import Memory
from cognitive.map_navigation import PauseMap
from cognitive.map_anchor import SpawnMapAnchor
from cognitive.spatial import SpatialVision
from cognitive.lantern_vision import LanternVision
folder=ROOT/'data/v2/v2_trial_99d348c7cb44486e';report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
memory=Memory(ROOT/'data/cognitive.sqlite');reference=memory.retrieve(report['scope'],kind='v2_spawn_anchor',include_global=False,limit=1)[0]
anchor=SpawnMapAnchor.load(reference['content'],ROOT);vision=LanternVision(ROOT);parser=PauseMap();maps=sorted(folder.glob('*-planning-map.jpg'));rows=[]
for action in report['actions']:
    if 'map_motion' not in action['metrics']:continue
    frame_path=ROOT/action['before']['frame'];number=int(frame_path.name.split('-')[0]);previous=[p for p in maps if int(p.name.split('-')[0])<number]
    if not previous:continue
    map_frame=previous[-1];state=parser.parse(cv2.imread(str(map_frame)));alignment=anchor.locate(state)
    if not alignment:continue
    frame=cv2.imread(str(frame_path));features=SpatialVision().entities(frame);objects=vision.detect(frame,features.get('player'))
    if not objects or not features.get('player') or features.get('enemy_count') or features.get('hazard_count'):continue
    point=anchor.project(state['player'],alignment)
    content={'run_id':report['run_id'],'anchor_id':anchor.identity,'actor_reference':point,'objects':objects,'frame':str(frame_path),'map_frame':str(map_frame),'historical_replay':True,'claim':'past object sighting from a paired observed map pose; not a claim of current object presence'}
    dedupe='v2:vantage:'+report['scope']+':'+anchor.identity+':'+str(round(point[0]/16))+':'+str(round(point[1]/16))
    mid=memory.remember('episodic','v2_object_vantage',report['scope'],content,Provenance(str(frame_path),method='historical_template_replay_with_paired_map_pose'),.85,'verified',dedupe=dedupe)
    rows.append({'memory_id':mid,**content})
memory.close();(ROOT/'evaluations/v2/object-vantage-replay.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps([{'actor':r['actor_reference'],'objects':[(o['kind'],round(o['confidence'],3)) for o in r['objects']],'frame':Path(r['frame']).name} for r in rows],ensure_ascii=False,indent=2))
