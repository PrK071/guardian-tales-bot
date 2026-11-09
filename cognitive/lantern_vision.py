"""Observed brazier/lantern appearances for the 1600x900 Passage 1 scene."""
from pathlib import Path
import cv2
import numpy as np

class LanternVision:
    def __init__(self,root):
        folder=Path(root)/'assets/v2'
        self.portable=cv2.imread(str(folder/'portable_brazier.png'))
        self.unlit=cv2.imread(str(folder/'standing_lantern_unlit.png'))
        path=Path(root)/'assets/v3/held_brazier.png';self.carried=cv2.imread(str(path)) if path.exists() else None
        path=Path(root)/'assets/v3/held_brazier_burning.png';self.burning=cv2.imread(str(path)) if path.exists() else None
        path=Path(root)/'assets/v3/lit_floor_pedestal.png';self.lit_base=cv2.imread(str(path)) if path.exists() else None
    @staticmethod
    def fire_mask(frame):return cv2.inRange(cv2.cvtColor(frame,cv2.COLOR_BGR2HSV),(8,120,180),(43,255,255))
    @staticmethod
    def matches(frame,template,threshold=.88,region=None,limit=8,mask=None):
        if template is None:return []
        x,y,w,h=region or (320,150,1080,670);search=frame[y:y+h,x:x+w]
        if min(search.shape[:2])==0 or search.shape[0]<template.shape[0] or search.shape[1]<template.shape[1]:return []
        scores=cv2.matchTemplate(cv2.cvtColor(search,cv2.COLOR_BGR2GRAY),cv2.cvtColor(template,cv2.COLOR_BGR2GRAY),cv2.TM_CCOEFF_NORMED,mask=mask);scores[~np.isfinite(scores)]=-1
        th,tw=template.shape[:2];result=[]
        for _ in range(limit):
            _,score,_,(px,py)=cv2.minMaxLoc(scores)
            if score<threshold:break
            result.append({'bbox':[x+px,y+py,tw,th],'confidence':float(score),'method':'recorded_gameplay_template'})
            scores[max(0,py-th//2):py+th//2+1,max(0,px-tw//2):px+tw//2+1]=-1
        return result
    def detect(self,frame,player=None,holding=False):
        if frame.shape[:2]!=(900,1600):return []
        objects=[]
        for template,kind in ((self.portable,'portable_brazier'),(self.unlit,'standing_lantern_unlit')):
            mask=None
            if kind=='portable_brazier' and template is not None:
                th,tw=template.shape[:2];mask=np.zeros((th,tw),np.uint8);cv2.ellipse(mask,(tw//2,th//2),(round(tw*.455),round(th*.453)),0,0,360,255,-1)
            for match in self.matches(frame,template,.84 if kind=='standing_lantern_unlit' else .88,region=[320,50,1080,770],mask=mask):
                x,y,w,h=match['bbox']
                if x+w/2>1090 and y>400:continue
                if kind=='standing_lantern_unlit' and player and abs(x+w/2-player[0])<60 and abs(y+h-player[1])<80:continue
                if kind=='portable_brazier' and holding and player and abs(x+w/2-player[0])<85 and player[1]-280<y+h<player[1]-35:continue
                if kind=='standing_lantern_unlit':
                    color=cv2.cvtColor(frame[y:y+h,x:x+w],cv2.COLOR_BGR2HSV)
                    # The account's stone rim occupies only 12.5% of the
                    # template; its dark socket and floor are saturated.
                    if np.mean((color[:,:,1]<65)&(color[:,:,2]>70))<.10:continue
                objects.append({'kind':kind,**match})
        if self.burning is not None:
            th,tw=self.burning.shape[:2];rim=np.zeros((th,tw),np.uint8)
            cv2.ellipse(rim,(tw//2,th//2),(round(tw*.455),round(th*.453)),0,0,360,255,-1);cv2.ellipse(rim,(tw//2,th//2),(round(tw*.31),round(th*.292)),0,0,360,0,-1);rim[:th//4]=0;rim[int(th*.8):]=0
            for match in self.matches(frame,self.burning,.86,region=[320,50,1080,770],mask=rim):
                x,y,w,h=match['bbox']
                if holding and player and abs(x+w/2-player[0])<85 and player[1]-280<y+h<player[1]-35:continue
                if not any(o['kind']=='portable_brazier' and abs(o['bbox'][0]-x)<40 and abs(o['bbox'][1]-y)<40 for o in objects):objects.append({'kind':'portable_brazier',**match,'method':'verified_burning_brazier_side_rim'})
        mask=self.fire_mask(frame);mask[:150]=0;mask[820:]=0;mask[:,:320]=0;mask[:,1400:]=0
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((7,7),np.uint8))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        lit=[]
        for contour in contours:
            x,y,w,h=cv2.boundingRect(contour)
            if not (15<=w<=115 and 30<=h<=160 and cv2.contourArea(contour)>180):continue
            core=cv2.inRange(hsv[y:y+h,x:x+w],(18,90,240),(43,255,255))
            if np.count_nonzero(core)<35:continue
            if holding and player and abs(x+w/2-player[0])<85 and player[1]-260<y+h<player[1]-60:continue
            below=hsv[y+h:min(900,y+h+90),max(0,int(x+w/2-40)):min(1600,int(x+w/2+40))]
            gray=cv2.inRange(below,(0,0,70),(180,90,230)) if below.size else np.zeros((1,1),np.uint8)
            if np.count_nonzero(gray)<150:continue
            lit.append({'kind':'standing_lantern_lit','bbox':[max(0,int(x+w/2-35)),y,70,min(900-y,h+80)],'confidence':.8,'method':'observed_flame_with_gray_brazier_below'})
        if self.lit_base is not None:
            # Wall sconces also have flame and gray pixels. Require the actual
            # floor pedestal observed in the lantern room, plus current fire.
            lit=[];fire=self.fire_mask(frame)
            for base in self.matches(frame,self.lit_base[:35],.94,region=[320,50,1080,770]):
                x,y,w,h=base['bbox'];h=self.lit_base.shape[0];base['bbox']=[x,y,w,h];x1=max(320,x-15);x2=min(1400,x+w+15);y1=max(50,y-170);y2=min(820,y+20)
                ys,xs=np.nonzero(fire[y1:y2,x1:x2])
                if len(xs)<100:continue
                center=[float(xs.mean()+x1),float(ys.mean()+y1)]
                if abs(center[0]-(x+w/2))>40:continue
                lit.append({'kind':'standing_lantern_lit','bbox':[x,max(50,y-120),w,h+min(120,y-50)],'fire_center':center,'pedestal_bbox':base['bbox'],'confidence':base['confidence'],'method':'floor_lantern_pedestal_with_current_fire'})
        objects=[o for o in objects if o['kind']!='standing_lantern_unlit' or not any(abs(o['bbox'][0]+o['bbox'][2]/2-(b['bbox'][0]+35))<45 and abs(o['bbox'][1]+o['bbox'][3]-(b['bbox'][1]+b['bbox'][3]))<90 for b in lit)]
        return objects+lit
    def held_match(self,frame,player):
        if self.portable is None or not player:return None
        x,y=player;region=[max(0,int(x-105)),max(150,int(y-270)),210,300];best=None
        for scale in (.6,.7,.8,.9,1.):
            for appearance in (self.portable,self.carried):
                if appearance is None:continue
                template=cv2.resize(appearance,None,fx=scale,fy=scale)
                if appearance is self.carried:
                    rx,ry,rw,rh=region;search=cv2.cvtColor(frame[ry:ry+rh,rx:rx+rw],cv2.COLOR_BGR2GRAY);th,tw=template.shape[:2]
                    if search.shape[0]<th or search.shape[1]<tw:continue
                    mask=np.zeros((th,tw),np.uint8);cv2.ellipse(mask,(tw//2,th//2),(round(tw*.455),round(th*.453)),0,0,360,255,-1)
                    scores=cv2.matchTemplate(search,cv2.cvtColor(template,cv2.COLOR_BGR2GRAY),cv2.TM_CCOEFF_NORMED,mask=mask);scores[~np.isfinite(scores)]=-1
                    _,score,_,(mx,my)=cv2.minMaxLoc(scores)
                    matches=[{'bbox':[rx+mx,ry+my,tw,th],'confidence':float(score),'method':'verified_carried_brazier_ellipse_mask'}] if score>=.70 else []
                else:matches=self.matches(frame,template,.65,region,limit=1)
                if matches and (best is None or matches[0]['confidence']>best['confidence']):best={**matches[0],'scale':scale}
        if self.carried is not None and (best is None or best['confidence']<.85):
            # Ignition replaces the wood texture with animated bright fire.
            # The lower stone rim remains visible and has a distinct pattern.
            rx,ry,rw,rh=region;search=cv2.cvtColor(frame[ry:ry+rh,rx:rx+rw],cv2.COLOR_BGR2GRAY);th,tw=self.carried.shape[:2]
            if search.shape[0]>=th and search.shape[1]>=tw:
                mask=np.zeros((th,tw),np.uint8);center=(tw//2,th//2)
                cv2.ellipse(mask,center,(round(tw*.455),round(th*.453)),0,0,360,255,-1);cv2.ellipse(mask,center,(round(tw*.31),round(th*.292)),0,0,360,0,-1);mask[:th//2]=0
                scores=cv2.matchTemplate(search,cv2.cvtColor(self.carried,cv2.COLOR_BGR2GRAY),cv2.TM_CCOEFF_NORMED,mask=mask);scores[~np.isfinite(scores)]=-1
                _,score,_,(mx,my)=cv2.minMaxLoc(scores)
                if score>=.70 and (best is None or score>best['confidence']):best={'bbox':[rx+mx,ry+my,tw,th],'confidence':float(score),'scale':1.,'method':'carried_burning_brazier_lower_stone_rim'}
        if self.burning is not None:
            # Independently verified ignited appearance. Use only the side rim:
            # the flame and its light change the bowl centre and lower shading.
            th,tw=self.burning.shape[:2];mask=np.zeros((th,tw),np.uint8)
            cv2.ellipse(mask,(tw//2,th//2),(round(tw*.455),round(th*.453)),0,0,360,255,-1)
            cv2.ellipse(mask,(tw//2,th//2),(round(tw*.31),round(th*.292)),0,0,360,0,-1)
            mask[:th//4]=0;mask[int(th*.8):]=0
            candidates=self.matches(frame,self.burning,.82,region,limit=1,mask=mask)
            if candidates and (best is None or candidates[0]['confidence']>best['confidence']):best={**candidates[0],'scale':1.,'method':'verified_burning_brazier_side_rim'}
        return best
    def held_fire_pixels(self,frame,player):
        if not player:return 0
        x,y=map(int,player);mask=self.fire_mask(frame)
        return int(np.count_nonzero(mask[max(150,y-270):max(151,y-75),max(320,x-75):min(1400,x+75)]))
    @staticmethod
    def carried_actor_visible(frame,held,pose_offset):
        x,y,w,h=held['bbox'];dx,dy=pose_offset;px=x+w/2+dx*w;py=y+dy*h
        roi=frame[max(150,round(y+h+4)):min(820,round(py+8)),max(320,round(px-42)):min(1400,round(px+42))]
        if not roi.size:return False
        hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
        return int(np.count_nonzero((hsv[:,:,1]<100)&(hsv[:,:,2]>140)))>=35
