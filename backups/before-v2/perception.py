from __future__ import annotations
from pathlib import Path
import hashlib, re, unicodedata
import cv2
import numpy as np
from .contracts import Observation, Provenance, now, uid

def normalize(text): return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))

class Interpreter:
    """Adds contextual evidence to the existing OCR/CV; uncertain fields stay null."""
    def __init__(self): self.last: Observation | None=None
    def interpret(self,frame,snapshot,enemy=None,frame_path=None) -> Observation:
        h,w=frame.shape[:2]; text=normalize(' '.join(word['text'] for word in snapshot.get('words',[])))
        scene=snapshot['scene']; stage=None; world=None; stage_observed=False
        match=re.search(r'mundo\s*(\d+)',text)
        if match: world=int(match[1])
        if scene in ('pausa','entrada','resultado'):
            passage=re.search(r'passagem\s*(\d+)',text)
            regular=re.search(r'(?<!\d)(\d{1,2})\s*[-–]\s*(\d{1,2})(?!\d)',text)
            if world and passage: stage=f'world:{world}:passage:{int(passage[1])}'
            elif regular: stage=f'world:{int(regular[1])}:stage:{int(regular[2])}'
            stage_observed=stage is not None
        # Continuous in-stage observations may inherit identity only in this
        # interpreter instance. Reopening a process does not inherit it blindly.
        if not stage and scene in ('jogo','dialogo','bloqueada') and self.last and self.last.stage and self.last.scene in ('pausa','jogo','dialogo','bloqueada'):
            stage=self.last.stage
        scope=stage or (f'world:{world}' if world else 'unknown')
        features={'world':world,'stage_observed':stage_observed,'stage_confidence':.95 if stage_observed else .85 if stage else 0,
                  'enemy_count':1 if enemy else 0,'enemy':[enemy[0]/w,enemy[1]/h] if enemy else None,'health':None,'minimap':None,
                  'stage_cleared':scene=='resultado' and stage_observed,'pause_available':scene=='jogo'}
        if scene=='jogo':
            hp=frame[int(.099*h):int(.115*h),int(.218*w):int(.265*w)]
            if hp.size:
                mask=cv2.inRange(cv2.cvtColor(hp,cv2.COLOR_BGR2HSV),(35,80,45),(90,255,255))
                features['health']=round(float(np.mean(np.any(mask>0,axis=0))),3)
            mini=frame[int(.015*h):int(.24*h),int(.008*w):int(.202*w)]
            hsv=cv2.cvtColor(mini,cv2.COLOR_BGR2HSV)
            floor=cv2.inRange(hsv,(20,55,45),(95,255,255))
            small=cv2.resize(floor,(32,20),interpolation=cv2.INTER_AREA)>100
            features['minimap']=np.packbits(small).tobytes().hex()
        center=frame[int(.20*h):int(.70*h),int(.24*w):int(.74*w)]
        gray=cv2.cvtColor(cv2.resize(center,(24,16)),cv2.COLOR_BGR2GRAY)
        features['visual_vector']=(gray//16).flatten().tolist()
        features['visual_hash']=hashlib.sha256(gray.tobytes()).hexdigest()[:20]
        features['counters']=re.findall(r'\b\d+\s*/\s*\d+\b',text)
        features['hazard_known']=False  # No validated general trap detector yet.
        certainty=.95 if scene in ('pausa','entrada','mapa','resultado','bloqueada') else .8 if scene=='jogo' else .4
        ob=Observation(uid('observation'),snapshot.get('at',now()),scene,certainty,scope,stage,text,features,frame_path,snapshot.get('blocked'),
                       Provenance('android:screencap',method='legacy_ocr+context_cv'))
        self.last=ob; return ob

def distance(a: Observation,b: Observation):
    va=a.features.get('visual_vector'); vb=b.features.get('visual_vector')
    if not va or not vb or len(va)!=len(vb): return 1.0
    return float(np.mean(np.abs(np.array(va,dtype=float)-np.array(vb,dtype=float)))/15)

class LegacyEnvironment:
    """Uses the same Bot and ADB instance on its existing worker thread."""
    def __init__(self,bot,root: Path):
        self.bot=bot; self.root=Path(root); self.interpreter=Interpreter(); self.last_frame=None
        (self.root/'data/evidence').mkdir(parents=True,exist_ok=True)
    def observe(self):
        frame,snap=self.bot.observe(); self.last_frame=frame
        enemy=self.bot.enemy_target(frame)
        path=self.root/'data/evidence'/('ob-'+str(snap['at']).replace('.','-')+'.jpg')
        if not cv2.imwrite(str(path),frame,[cv2.IMWRITE_JPEG_QUALITY,75]):raise OSError('Cannot persist observation evidence')
        return self.interpreter.interpret(frame,snap,enemy,str(path))
    def execute(self,action):
        action.validate()
        if action.op=='observe': return
        self.bot.execute(action.legacy(),record=False)
    def route_candidates(self,observation):
        if self.last_frame is None or observation.scene!='jogo': return []
        matches=[]
        for path in (self.root/'routes').glob('*.json'):
            import json
            try: route=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError): continue
            steps=route.get('steps',[])
            if not steps or not steps[0].get('anchor'): continue
            if route.get('scope')!=observation.scope or not route.get('end_anchor'):continue
            anchor=(self.root/'routes'/steps[0]['anchor']).resolve()
            if not anchor.is_relative_to((self.root/'routes').resolve()): continue
            img=cv2.imread(str(anchor))
            if img is None: continue
            score=self.bot.checkpoint_similarity(self.last_frame,img,steps[0].get('roi'))
            if score>=max(.95,steps[0].get('min_similarity',.91)):
                matches.append({'id':path.stem,'scope':observation.scope,'score':score,'steps':steps,'end_anchor':route.get('end_anchor'),'stage_complete':False,'version':hashlib.sha256(path.read_bytes()).hexdigest()[:16]})
        return sorted(matches,key=lambda item:item['score'],reverse=True)
    def checkpoint_matches(self,observation,anchor,threshold=.91):
        if not anchor or self.last_frame is None: return False
        path=(self.root/'routes'/anchor).resolve()
        if not path.is_relative_to((self.root/'routes').resolve()): raise ValueError('Invalid checkpoint path')
        frame=cv2.imread(str(path))
        if frame is None: return False
        return self.bot.checkpoint_similarity(self.last_frame,frame)>=threshold
