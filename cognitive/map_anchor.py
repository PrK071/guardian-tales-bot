"""Align the observed pause-map silhouette to a verified spawn-room reference.

This estimates only UI scale/translation. It does not invent unexplored rooms,
perform SLAM or assume the current marker is still at the initial position.
"""
from pathlib import Path
import hashlib,json
import cv2
import numpy as np

class SpawnMapAnchor:
    def __init__(self,template,origin,spawn_point=None):
        if template is None or template.ndim!=2 or min(template.shape)<30:raise ValueError('Invalid map anchor image')
        self.template=template;self.origin=list(map(float,origin));self.spawn_point=list(map(float,spawn_point)) if spawn_point is not None else None;self.floor_reference=None
        self.identity=hashlib.sha256(template.tobytes()+json.dumps([self.origin,self.spawn_point]).encode()).hexdigest()
    @classmethod
    def from_map(cls,state):
        floor=state['floor'];px,py=state['player'];x,y,w,h=state['bbox'];bottom=y+h
        if not 0<=bottom-py<35:raise ValueError('Spawn anchor requires an observed initial marker inside the bottom stem')
        left=max(0,int(px-80));top=max(0,int(bottom-210));right=min(floor.shape[1],left+160);end=min(floor.shape[0],bottom+5)
        return cls(floor[top:end,left:right].copy(),[left,top],[px,py])
    def save(self,path):
        if not cv2.imwrite(str(path),self.template):raise OSError('Cannot save observed spawn anchor')
        return {'path':str(path),'origin':self.origin,'spawn_point':self.spawn_point,'identity':self.identity,'scope':'world:1:passage:1','method':'observed_spawn_room_silhouette'}
    @classmethod
    def load(cls,data,root):
        path=Path(data['path']).resolve();root=Path(root).resolve()
        if data.get('scope')!='world:1:passage:1' or not path.is_relative_to(root):raise ValueError('Map anchor path/scope invalid')
        anchor=cls(cv2.imread(str(path),cv2.IMREAD_GRAYSCALE),data['origin'],data.get('spawn_point'))
        if data.get('identity') and anchor.identity!=data['identity']:raise ValueError('Map anchor content hash mismatch')
        metadata=root/'assets/v3/passage1_full_map_reference.json'
        if metadata.exists():
            reference=json.loads(metadata.read_text());image=(root/reference['path']).resolve()
            if reference.get('anchor_identity')==anchor.identity and image.is_relative_to(root):
                if hashlib.sha256(image.read_bytes()).hexdigest()!=reference['sha256']:raise ValueError('Full map reference hash mismatch')
                anchor.floor_reference=(cv2.imread(str(image),cv2.IMREAD_GRAYSCALE),reference['anchor_alignment'])
        return anchor
    def locate(self,state):
        floor=state['floor'];x,y,w,h=state['bbox'];left=max(0,x-8);top=max(0,y-8)
        search=floor[top:min(floor.shape[0],y+h+8),left:min(floor.shape[1],x+w+8)]
        candidates=[]
        def evaluate(scale):
            template=cv2.resize(self.template,None,fx=scale,fy=scale,interpolation=cv2.INTER_NEAREST)
            th,tw=template.shape
            if th>=search.shape[0] or tw>=search.shape[1]:return
            scores=cv2.matchTemplate(search,template,cv2.TM_CCOEFF_NORMED)
            remaining=scores.copy()
            for _ in range(3):
                _,score,_,point=cv2.minMaxLoc(remaining)
                if score<.7:break
                ax,ay=point;marker=state.get('player_marker_bbox')
                if marker:
                    mx,my,mw,mh=marker;cx=left+ax;cy=top+ay
                    ix1=max(0,mx-cx);iy1=max(0,my-cy);ix2=min(tw,mx+mw-cx);iy2=min(th,my+mh-cy)
                    if ix1<ix2 and iy1<iy2:
                        mask=np.ones((th,tw),bool);mask[iy1:iy2,ix1:ix2]=False
                        if np.mean(mask)>.7:
                            a=template[mask].astype(float);b=search[ay:ay+th,ax:ax+tw][mask].astype(float)
                            if np.std(a)>0 and np.std(b)>0:score=float(np.corrcoef(a,b)[0,1])
                candidates.append((float(score),float(scale),point,tw,th,scores))
                remaining[max(0,int(ay-th*.65)):int(ay+th*.65)+1,max(0,int(ax-tw*.65)):int(ax+tw*.65)+1]=-1
        for scale in np.arange(.55,1.151,.05):evaluate(float(scale))
        if not candidates:return None
        coarse=max(candidates,key=lambda item:item[0])[1]
        for scale in np.arange(max(.5,coarse-.04),min(1.2,coarse+.04)+.001,.01):evaluate(float(scale))
        score,scale,(ax,ay),tw,th,scores=max(candidates,key=lambda item:item[0])
        second=max((c[0] for c in candidates if abs(c[2][0]-ax)>tw*.65 or abs(c[2][1]-ay)>th*.65),default=-1)
        if score<.90 or score-second<.035:return None
        return {'score':score,'second_score':second,'scale':scale,'top_left':[left+ax,top+ay],'source_origin':self.origin}
    @staticmethod
    def project(point,alignment):
        return [(point[i]-alignment['top_left'][i])/alignment['scale']+alignment['source_origin'][i] for i in range(2)]
    def restore_marker_floor(self,state,alignment):
        """Restore known reference floor only beneath this observed opaque icon."""
        marker=state.get('player_marker_bbox')
        if not marker or alignment['score']<.98:return False
        x,y,w,h=map(int,marker);height,width=state['floor'].shape
        x1=max(0,x);y1=max(0,y);x2=min(width,x+w);y2=min(height,y+h)
        yy,xx=np.mgrid[y1:y2,x1:x2];tx=(xx-alignment['top_left'][0])/alignment['scale'];ty=(yy-alignment['top_left'][1])/alignment['scale'];reference=self.template
        if self.floor_reference:
            reference,source=self.floor_reference
            tx=tx*source['scale']+source['top_left'][0];ty=ty*source['scale']+source['top_left'][1]
        tx=np.rint(tx).astype(int);ty=np.rint(ty).astype(int)
        valid=(tx>=0)&(ty>=0)&(tx<reference.shape[1])&(ty<reference.shape[0]);known=np.zeros(valid.shape,bool);known[valid]=reference[ty[valid],tx[valid]]>0
        state['floor'][y1:y2,x1:x2][known]=255
        state['known_floor_restored_under_pin']={'bbox':marker,'anchor_identity':self.identity,'score':alignment['score'],'pixels':int(np.count_nonzero(known))}
        return True
    def motion(self,before,after,direction):
        a=before.get('anchor_alignment') or self.locate(before);b=after.get('anchor_alignment') or self.locate(after)
        if not a or not b:return {'verified':False,'reason':'spawn_silhouette_alignment_uncertain','before_alignment':a,'after_alignment':b}
        p=self.project(before['player'],a);q=self.project(after['player'],b);dx=q[0]-p[0];dy=q[1]-p[1]
        vx,vy={'up':(0,-1),'down':(0,1),'left':(-1,0),'right':(1,0)}[direction];progress=dx*vx+dy*vy
        return {'verified':bool(progress>3.5),'dx':dx,'dy':dy,'direction_progress':progress,'before':p,'after':q,'before_alignment':a,'after_alignment':b,'units':'pixels in the observed spawn reference, not world meters'}
    def is_spawn(self,state):
        if self.spawn_point is None:return False
        alignment=self.locate(state)
        if not alignment:return False
        point=self.project(state['player'],alignment)
        return bool(np.linalg.norm(np.asarray(point)-np.asarray(self.spawn_point))<16)
