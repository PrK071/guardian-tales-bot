"""Historical-image research-to-hypothesis evidence; sends no Android input."""
from pathlib import Path
import json,sys,time
import cv2
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from cognitive.memory import Memory
from cognitive.contracts import Provenance
from cognitive.spatial import SpatialVision
from cognitive.stage_v2 import compile_solution
memory=Memory(ROOT/'data/cognitive.sqlite');scope='world:1:passage:1'
content={'scope':scope,'validation':'reported','sources':[{'url':'https://guardian-tales.fandom.com/wiki/Kanterbury_Forest_Passage_1','method':'web_text_read_during_v2_investigation','snippet':'Reported objective: defeat the monsters. A junction offers a rock-blocked branch and a combat branch. A bomb or burning torch is described as a way to open the rocks. These are hypotheses until the current game confirms them.'}]}
memory.remember('semantic','research',scope,content,Provenance(content['sources'][0]['url'],method='web_text_paraphrase_not_video_analysis'),.55,'reported',dedupe='v2:passage1:wiki-reported')
path=ROOT/'data/v2/v2_calibration_d0a257a06a5846b3/0109-before-pausa.jpg'
features=SpatialVision().entities(cv2.imread(str(path)));features.pop('floor_mask')
kinds={e['kind'] for e in features['entities']};memories=memory.retrieve(scope,kind='research',include_global=False,limit=3)
solution=compile_solution(memories,scope,{'rock':'rock_obstacle_candidate' in kinds,'bomb':'bomb_candidate' in kinds})
report={'kind':'historical_image_plus_reported_web_source','frame':str(path),'features':features,'solution':solution,'actions_executed':0,'puzzle_solved':False,'limitation':'Object classes are appearance hypotheses; pickup, throw and rock removal still require real validation.'}
(ROOT/'evaluations/v2/research-evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
memory.close();print(json.dumps({'object_kinds':sorted(kinds),'compiled_hypothesis':solution,'puzzle_solved':False},ensure_ascii=False))
