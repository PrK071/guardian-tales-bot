"""Pull long visible segments from V2 BFS; keep floor clearance and checkpoints."""
import math
import cv2
import numpy as np
from ..map_navigation import PauseMap

def clear_line(clearance,start,end,margin,start_escape=False):
    distance=math.dist(start,end);steps=max(2,math.ceil(distance)+1)
    points=np.linspace(start,end,steps);x=np.rint(points[:,0]).astype(int);y=np.rint(points[:,1]).astype(int)
    valid=(x>=0)&(x<clearance.shape[1])&(y>=0)&(y<clearance.shape[0])
    # Pixel centers are rounded to the raster. A half-pixel tolerance avoids
    # rejecting a marker at clearance11 when scaled margin is11.28; it never
    # permits a ray through void or an actual wall.
    if not np.all(valid):return False
    values=clearance[y,x];threshold=max(0,margin-.5)
    if np.all(values>threshold):return True
    # A legitimate spawn can be 1-2 raster pixels inside the conservative
    # clearance margin. Permit only a short, monotone escape into full
    # clearance, never approach a wall or relax the rest of the segment.
    if not start_escape or values[0]<=0:return False
    good=np.flatnonzero(values>threshold)
    if not len(good):return False
    first=int(good[0]);prefix=values[:first+1]
    if math.dist(points[0],points[first])>margin:return False
    if np.any(prefix<values[0]-.5) or np.any(np.diff(prefix)<-.6):return False
    return bool(np.all(values[first:]>threshold))

class SegmentPlanner:
    def __init__(self,reference_pixels_per_ms):
        if not math.isfinite(reference_pixels_per_ms) or reference_pixels_per_ms<=0:raise ValueError('Measured movement calibration required')
        self.speed=reference_pixels_per_ms
    def plan(self,state,target,margin=None):
        parser=PauseMap();scale=state.get('map_scale',1.);margin=12*scale if margin is None else margin
        if not math.isfinite(margin) or margin<=0:raise ValueError('Positive measured floor clearance required')
        # V2's majority-cell grid may admit a cell whose center is too close
        # to a corner. V3 needs individually clear centers for long LOS holds.
        path=parser.path(state,target,cell=max(1,round(2*scale)),margin=margin,strict_centers=True)
        clearance=cv2.distanceTransform(state['floor'],cv2.DIST_L2,5)
        # Preserve measured geometry; no line may cut a staircase corner or wall.
        route=[state['player'],*path[1:]];knots=[route[0]];index=0
        def octile_options(start,end):
            sx,sy=start;ex,ey=end;dx=ex-sx;dy=ey-sy;ax=abs(dx);ay=abs(dy);ux=1 if dx>=0 else -1;uy=1 if dy>=0 else -1
            if min(ax,ay)<=2*scale:
                # Ignore sub-cell lateral snapping, rather than sending an
                # unsupported shallow analogue angle or a 40ms microstep.
                return [[[sx,ey] if ay>=ax else [ex,sy]]]
            small=min(ax,ay)
            diagonal=[sx+ux*small,sy+uy*small]
            dominant=[ex-ux*small,sy] if ax>ay else [sx,ey-uy*small]
            return [[diagonal,end],[dominant,end],[[ex,sy],end],[[sx,ey],end]]
        while index<len(route)-1:
            chosen=None
            for candidate in range(len(route)-1,index,-1):
                start=knots[-1];valid=[]
                for option in octile_options(start,route[candidate]):
                    points=[start]+[p for i,p in enumerate(option) if math.dist(p,start if i==0 else option[i-1])>.01]
                    if len(points)<2:continue
                    if all(clear_line(clearance,a,b,margin,start_escape=index==0 and n==0) for n,(a,b) in enumerate(zip(points,points[1:]))):
                        valid.append((sum(math.dist(a,b) for a,b in zip(points,points[1:])),points[1:]))
                if valid:chosen=(candidate,min(valid,key=lambda x:x[0])[1]);break
            if chosen is None:raise ValueError('No eight-direction segment with observed player clearance')
            index,points=chosen;knots.extend(points)
        segments=[]
        for start,end in zip(knots,knots[1:]):
            dx,dy=end[0]-start[0],end[1]-start[1];distance=math.hypot(dx,dy)
            if distance<2*scale:continue
            duration=distance/scale/self.speed
            # The 30s input envelope is a safety ceiling, not a short-step policy.
            count=max(1,math.ceil(duration/30000))
            for n in range(count):
                a=[start[0]+dx*n/count,start[1]+dy*n/count];b=[start[0]+dx*(n+1)/count,start[1]+dy*(n+1)/count]
                segments.append({'start':a,'end':b,'direction':[dx/distance,dy/distance],'duration_ms':max(40,duration/count),'reference_distance':distance/scale/count,'evidence':'line entirely inside observed floor with wall clearance'})
        return {'segments':segments,'original_grid_points':len(path),'checkpoints':knots,'target':list(target),'calibrated_reference_pixels_per_ms':self.speed,'unobserved_space_crossed':False}
