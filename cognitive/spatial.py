"""Local, image-grounded state. Pixel coordinates are not metric world coordinates."""
from __future__ import annotations
from dataclasses import asdict,dataclass
import hashlib,math
from pathlib import Path
import cv2
import numpy as np

@dataclass
class Entity:
    kind:str
    bbox:list[int]
    confidence:float
    method:str
    @property
    def center(self):x,y,w,h=self.bbox;return x+w/2,y+h/2

class SpatialVision:
    def __init__(self):
        self.last_player=None
        path=Path(__file__).resolve().parents[1]/'assets/v3/knight_helmet_north.png'
        self.helmet_north=cv2.imread(str(path)) if path.exists() else None
        self.helmets=[cv2.imread(str(p)) for p in path.parent.glob('knight_helmet_*.png')]
        occlusion=path.parent/'knight_occluded_by_follower.png';self.occluded_helmet=cv2.imread(str(occlusion)) if occlusion.exists() else None
        self.occluded_helmets=[(cv2.imread(str(path.parent/name)),offset) for name,offset in [('knight_occluded_by_follower.png',(48.5,96)),('knight_occluded_by_follower_bob.png',(48.5,93))] if (path.parent/name).exists()]

    @staticmethod
    def _floor_mask(hsv):
        h,w=hsv.shape[:2];floor=cv2.inRange(hsv,(0,75,65),(25,225,175));floor[:int(.15*h)]=0;floor[int(.86*h):]=0
        return cv2.morphologyEx(floor,cv2.MORPH_CLOSE,np.ones((13,13),np.uint8))
    @staticmethod
    def floor_mask(frame):return SpatialVision._floor_mask(cv2.cvtColor(frame,cv2.COLOR_BGR2HSV))
    @staticmethod
    def scene(frame):
        h,w=frame.shape[:2];hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        continue_roi=hsv[int(.87*h):int(.95*h),int(.82*w):int(.97*w)]
        yellow=cv2.inRange(continue_roi,(18,100,140),(40,255,255))
        if np.mean(yellow>0)>.35:return 'pausa'
        hud=hsv[int(.085*h):int(.12*h),int(.21*w):int(.33*w)]
        if np.mean(cv2.inRange(hud,(35,80,45),(90,255,255))>0)>.025:return 'jogo'
        return 'unknown'
    def entities(self,frame):
        h,w=frame.shape[:2];hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV);entities=[]
        # Silver helmet: calibrated player appearance, separated from HUD portraits.
        mask=cv2.inRange(hsv,(0,0,140),(180,80,255));mask[:int(.17*h)]=0
        mask[:, :int(.20*w)]=0;mask[:,int(.82*w):]=0;mask[int(.76*h):]=0
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        candidates=[]
        for contour in contours:
            x,y,bw,bh=cv2.boundingRect(contour);area=cv2.contourArea(contour)
            if 25<=bw<=100 and 25<=bh<=115 and area>350:candidates.append((x,y,bw,bh,area))
        reference=self.last_player or (w*.5,h*.495)
        if candidates:
            # The bright component sometimes includes the sword and sometimes
            # only the helmet. Its bottom is therefore not a stable foot point.
            # Current costume/resolution calibration: helmet top to feet = 95px.
            p=min(candidates,key=lambda b:math.hypot(b[0]+b[2]/2-reference[0],b[1]+95-reference[1]))
            self.last_player=(p[0]+p[2]/2,p[1]+95)
            entities.append(Entity('player',[p[0],p[1],p[2],95],.82,'silver_helmet_top_plus_observed_95px_height'))
        refine_actor=not candidates or math.dist(self.last_player,(w*.5,h*.495))>12
        for template in (self.helmets if refine_actor and not getattr(self,'skip_helmet_templates',False) else []):
            # Adjacent silver rocks or white tool bubbles merge with the helmet
            # in color segmentation. The observed north-facing helmet still
            # identifies the character independently of those components.
            th,tw=template.shape[:2];region=frame[265:465,650:950]
            oval=np.zeros((th,tw),np.uint8);cv2.ellipse(oval,(tw//2,28),(30,27),0,0,360,255,-1);oval[30:]=0
            scores=cv2.matchTemplate(cv2.cvtColor(region,cv2.COLOR_BGR2GRAY),cv2.cvtColor(template[:30],cv2.COLOR_BGR2GRAY),cv2.TM_CCOEFF_NORMED,mask=oval[:30]);scores[~np.isfinite(scores)]=-1
            _,score,_,(tx,ty)=cv2.minMaxLoc(scores)
            if score>=.92 and score>max([e.confidence for e in entities if e.kind=='player' and e.method=='observed_helmet_template_with_calibrated_foot'] or [0]):
                tx+=650;ty+=265;self.last_player=(tx+tw/2,ty+95);entities=[e for e in entities if e.kind!='player'];entities.append(Entity('player',[tx,ty,tw,95],float(score),'observed_helmet_template_with_calibrated_foot'))
        if refine_actor and not getattr(self,'skip_helmet_templates',False) and not any(e.kind=='player' and e.method=='observed_helmet_template_with_calibrated_foot' for e in entities):
            # Actual silver edge/red plume appearances during follower overlap,
            # each with its independently measured foot offset (idle bob).
            for appearance,offset in self.occluded_helmets:
                scores=cv2.matchTemplate(frame[265:465,650:950],appearance,cv2.TM_CCOEFF_NORMED)
                _,score,_,(tx,ty)=cv2.minMaxLoc(scores);tx+=650;ty+=265;foot=[tx+offset[0],ty+offset[1]]
                previous=max([e.confidence for e in entities if e.kind=='player' and e.method=='observed_partial_helmet_with_calibrated_foot'] or [0])
                if score>=.92 and score>previous and math.dist(foot,(w*.5,h*.495))<35:
                    self.last_player=tuple(foot);entities=[e for e in entities if e.kind!='player'];entities.append(Entity('player',[tx,ty,89,offset[1]],float(score),'observed_partial_helmet_with_calibrated_foot'))
        # The observed HP fill stays bright as its width shrinks. Dark cave
        # pixels at V~90 were producing false bars along rock/void boundaries.
        red=cv2.inRange(hsv,(0,160,160),(8,255,255))|cv2.inRange(hsv,(173,160,160),(180,255,255));bars=[]
        contours,_=cv2.findContours(red,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);bar_keys=set()
        for contour in contours:
            x,y,bw,bh=cv2.boundingRect(contour)
            if x<535 and y<150:continue  # Observed party portraits/counters, not world enemy bars.
            if x>900 and y<90:continue  # Resource-counter glyphs have red antialiasing.
            if (x+bw/2>1090 and y>400) or (x+bw/2<400 and y>500):continue
            # Real enemies can enter from above the viewport, and one-pixel
            # remaining fills are still real bars. HUD portraits stay excluded
            # above; the full dark-bar structure below remains mandatory.
            if .20*w<x<.86*w and 0<=y<.77*h and 1<=bw<=170 and 6<=bh<=16:
                # HP fill is a solid rectangle; the follower's red hair can
                # have the same bounding size and a dark outline below it.
                if np.mean(red[y:y+bh,x:x+bw]>0)<.80:continue
                # Hit highlights can desaturate the last 2-3 fill rows. Find
                # three contiguous dark border rows just below the red fill,
                # still requiring the full 45..180px bar structure.
                border_y=next((by for by in range(y+bh,min(h-2,y+bh+7)) if np.mean(np.max(frame[by:by+3,x:x+bw],axis=2)<85)>.85),None)
                if y<150:
                    bottom=frame[y+bh:min(h,y+bh+5),x:x+bw]
                    border_y=y+bh+1 if bottom.size and np.mean(np.max(bottom,axis=2)<85)>=.70 else None
                # A real enemy bar can overlap the knight at melee range.
                # Reject by bar structure/HUD region, not distance to player.
                if border_y is None:continue
                row=np.max(frame[border_y+1],axis=1)<85;center=int(x+bw/2)
                left=right=center
                while left>max(0,center-180) and row[left-1]:left-=1
                while right<min(w-1,center+180) and row[right+1]:right+=1
                full_width=right-left+1
                if not 45<=full_width<=180:continue
                key=(round(left/5),round(y/5))
                if key in bar_keys:continue
                bar_keys.add(key)
                entities.append(Entity('enemy',[left,max(0,y-85),full_width,90],.85,'red_remaining_hp_with_full_dark_bar'))
                bars.append({'bbox':[left,y,full_width,bh],'red_area':int(np.count_nonzero(red[y:y+bh,left:right+1]))})
        # Moving spike pillars: dark blue body + pale metal, observed in this cave.
        blue=cv2.inRange(hsv,(90,35,30),(130,230,165));blue[:int(.16*h)]=0;blue[int(.87*h):]=0
        blue=cv2.morphologyEx(blue,cv2.MORPH_CLOSE,np.ones((9,9),np.uint8))
        contours,_=cv2.findContours(blue,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x,y,bw,bh=cv2.boundingRect(contour)
            if 35<=bw<=140 and 55<=bh<=190 and cv2.contourArea(contour)>1000:
                entities.append(Entity('hazard',[x,y,bw,bh],.72,'observed_cave_blue_spike_shape'))
        # Appearance hypotheses scoped to the observed Passage 1 cave. Neither
        # shape is automatically a proven puzzle solution or interaction target.
        rocks=cv2.inRange(hsv,(55,20,80),(72,105,250));rocks[:180]=0;rocks[820:]=0
        flowers=cv2.inRange(hsv,(123,70,105),(163,240,255));flowers[:135]=0;flowers[820:]=0
        for mask,kind,area_min in ((rocks,'rock_obstacle_candidate',5000),(flowers,'bomb_candidate',1200)):
            components,_=cv2.findContours(cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((7,7),np.uint8)),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            for contour in components:
                x,y,bw,bh=cv2.boundingRect(contour)
                if 60<=bw<=350 and 50<=bh<=450 and cv2.contourArea(contour)>area_min:
                    entities.append(Entity(kind,[x,y,bw,bh],.70,'passage1_observed_color_shape_hypothesis'))
        # Local walkable cave-floor hypothesis: low-value brown, excluding void.
        floor=self._floor_mask(hsv)
        scene=self.scene(frame)
        if scene!='jogo':entities=[]
        hp=hsv[int(.099*h):int(.115*h),int(.218*w):int(.265*w)]
        # Depleted health uses a dark green background (observed V~85).
        # Count the bright fill, not that background.
        health=round(float(np.mean(np.any(cv2.inRange(hp,(35,80,120),(90,255,255))>0,axis=0))),3) if scene=='jogo' else None
        if scene=='pausa':
            hp=hsv[int(.111*h):int(.120*h),int(.0775*w):int(.15375*w)]
            health=round(float(np.mean(np.any(cv2.inRange(hp,(35,80,120),(90,255,255))>0,axis=0))),3)
        features={'entities':[asdict(entity) for entity in entities],'player':list(self.last_player) if any(e.kind=='player' for e in entities) else None,
                  'enemy_count':sum(e.kind=='enemy' for e in entities),'hazard_count':sum(e.kind=='hazard' for e in entities),
                  'scene':scene,'health':health,'enemy_bars':bars if scene=='jogo' else [],'enemy_red_area':sum(bar['red_area'] for bar in bars) if scene=='jogo' else 0,'floor_fraction':float(np.mean(floor>0)),'floor_mask':floor}
        # The focused enemy's large HP bar persists while its small world bar
        # flashes pink/white during a hit. It proves combat presence, never a
        # fabricated target position. This ROI excludes party portraits.
        focus=None
        if scene=='jogo':
            roi=red[140:185,590:1010];components,_=cv2.findContours(roi,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            for contour in components:
                fx,fy,fw,fh=cv2.boundingRect(contour)
                if 1<=fw<=405 and 18<=fh<=36 and np.mean(roi[fy:fy+fh,fx:fx+fw]>0)>.80:
                    border=frame[140+fy+fh:140+fy+fh+7,590+fx:590+fx+fw]
                    if border.size and np.mean(np.max(border,axis=2)<85)>.65:
                        focus={'bbox':[590+fx,140+fy,fw,fh],'red_area':int(np.count_nonzero(roi[fy:fy+fh,fx:fx+fw])),'method':'focused_enemy_red_hp_with_dark_lower_border'};break
        features['focused_enemy_hp']=focus;features['combat_present']=bool(features['enemy_count'] or focus)
        if features['scene']=='pausa':
            green=cv2.inRange(hsv,(25,55,75),(95,255,255));green[:int(.20*h)]=0;green[:, :int(.25*w)]=0;green[int(.80*h):]=0
            contours,_=cv2.findContours(green,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                contour=max(contours,key=cv2.contourArea);x,y,bw,bh=cv2.boundingRect(contour)
                if cv2.contourArea(contour)>1000:
                    features['observed_map']={'bbox':[x,y,bw,bh],'mask_sha256':hashlib.sha256(green.tobytes()).hexdigest(),
                                              'scope':'current screenshot coordinates, not a globally aligned map','confidence':.9}
        return features
    @staticmethod
    def motion(before,after,before_player=None,after_player=None):
        h,w=before.shape[:2];scale=.4
        a=cv2.resize(cv2.cvtColor(before,cv2.COLOR_BGR2GRAY),None,fx=scale,fy=scale)
        b=cv2.resize(cv2.cvtColor(after,cv2.COLOR_BGR2GRAY),None,fx=scale,fy=scale)
        mask=np.zeros_like(a);mask[int(.17*h*scale):int(.74*h*scale),int(.22*w*scale):int(.78*w*scale)]=255
        mask[int(.33*h*scale):int(.56*h*scale),int(.42*w*scale):int(.59*w*scale)]=0
        points=cv2.goodFeaturesToTrack(a,maxCorners=180,qualityLevel=.02,minDistance=8,mask=mask)
        result={'background_dx':0.,'background_dy':0.,'inliers':0,'confidence':0.,'player_dx':None,'player_dy':None}
        # Camera translations can exceed a sparse tracker's capture range.
        # Independent flank correlations exclude the screen-centered player.
        shifts=[]
        for x1,x2 in ((.25,.44),(.54,.75)):
            box=(int(x1*w),int(.17*h),int(x2*w),int(.72*h))
            aa=cv2.cvtColor(before[box[1]:box[3],box[0]:box[2]],cv2.COLOR_BGR2GRAY).astype(np.float32)
            bb=cv2.cvtColor(after[box[1]:box[3],box[0]:box[2]],cv2.COLOR_BGR2GRAY).astype(np.float32)
            shift,response=cv2.phaseCorrelate(aa,bb)
            if response>.06:shifts.append((shift,response))
        if len(shifts)==2 and max(s[1] for s in shifts)>.25 and math.dist(shifts[0][0],shifts[1][0])<12:
            total=sum(s[1] for s in shifts)
            dx=sum(s[0][0]*s[1] for s in shifts)/total;dy=sum(s[0][1]*s[1] for s in shifts)/total
            result.update(background_dx=round(dx,2),background_dy=round(dy,2),confidence=round(min(1,max(s[1] for s in shifts)),3),method='two_flank_phase_consensus')
        if points is not None and len(points)>=8:
            moved,status,_=cv2.calcOpticalFlowPyrLK(a,b,points,None,winSize=(25,25),maxLevel=3)
            if moved is not None:
                valid=status.flatten()>0;delta=(moved[valid]-points[valid]).reshape(-1,2)/scale
                if len(delta)>=8:
                    median=np.median(delta,axis=0);inliers=np.linalg.norm(delta-median,axis=1)<8
                    if np.count_nonzero(inliers)>=8 and result['confidence']==0:
                        median=np.median(delta[inliers],axis=0)
                        result.update(background_dx=round(float(median[0]),2),background_dy=round(float(median[1]),2),inliers=int(np.count_nonzero(inliers)),confidence=round(float(np.mean(inliers)),3))
        if result['confidence']==0:
            # Continuous holds can translate farther than LK's capture range.
            # Match static world descriptors, excluding the HUD and actor,
            # and require a majority translation consensus before accepting it.
            aa=cv2.cvtColor(before,cv2.COLOR_BGR2GRAY);bb=cv2.cvtColor(after,cv2.COLOR_BGR2GRAY)
            world=np.zeros_like(aa);world[int(.17*h):int(.72*h),int(.22*w):int(.78*w)]=255
            world[int(.27*h):int(.56*h),int(.42*w):int(.59*w)]=0
            orb=cv2.ORB_create(nfeatures=900);ka,da=orb.detectAndCompute(aa,world);kb,db=orb.detectAndCompute(bb,world)
            if da is not None and db is not None:
                matches=[m for m in cv2.BFMatcher(cv2.NORM_HAMMING,crossCheck=True).match(da,db) if m.distance<45]
                if len(matches)>=12:
                    delta=np.array([np.array(kb[m.trainIdx].pt)-np.array(ka[m.queryIdx].pt) for m in matches]);median=np.median(delta,axis=0);inliers=np.linalg.norm(delta-median,axis=1)<5
                    if np.count_nonzero(inliers)>=12 and np.mean(inliers)>=.60:
                        median=np.median(delta[inliers],axis=0)
                        result.update(background_dx=round(float(median[0]),2),background_dy=round(float(median[1]),2),inliers=int(np.count_nonzero(inliers)),confidence=round(float(np.mean(inliers)),3),method='static_world_orb_translation_consensus')
        if before_player and after_player:
            result['player_dx']=round(after_player[0]-before_player[0],2);result['player_dy']=round(after_player[1]-before_player[1],2)
        result['effective_dx']=round((result['player_dx'] or 0)-result['background_dx'],2)
        result['effective_dy']=round((result['player_dy'] or 0)-result['background_dy'],2)
        result['moved']=bool(math.hypot(result['effective_dx'],result['effective_dy'])>8 and (result['confidence']>.25 or before_player and after_player))
        return result
