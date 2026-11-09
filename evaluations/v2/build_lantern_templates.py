"""CV templates cropped from this account's recorded gameplay, not guide pixels."""
from pathlib import Path
import cv2,json,hashlib
ROOT=Path(__file__).resolve().parents[2];folder=ROOT/'assets/v2';folder.mkdir(parents=True,exist_ok=True)
definitions=[('portable_brazier','data/v2/v2_trial_99d348c7cb44486e/0225-before-move.jpg',[873,150,110,106]),('standing_lantern_unlit','data/v2/v2_trial_99d348c7cb44486e/0315-before-move.jpg',[378,234,67,91])]
rows=[]
for name,source,bbox in definitions:
    frame=cv2.imread(str(ROOT/source));x,y,w,h=bbox;target=folder/(name+'.png')
    if frame is None or not cv2.imwrite(str(target),frame[y:y+h,x:x+w]):raise RuntimeError('Cannot derive '+name)
    rows.append({'name':name,'source_frame':source,'source_sha256':hashlib.sha256((ROOT/source).read_bytes()).hexdigest(),'bbox':bbox,'template':str(target.relative_to(ROOT)),'template_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'label_validation':'appearance matched to video; interaction not yet validated in this account'})
(ROOT/'knowledge/v2_lantern_templates.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(rows,ensure_ascii=False))
