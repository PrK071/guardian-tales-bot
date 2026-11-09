"""A short frontier extension only through floor visible in the live image."""
import math
import cv2
from ..spatial import SpatialVision
from .continuous import ContinuousActions

def visible_floor_horizon(frame,features,direction,max_pixels=260,extra_obstacles=(),clearance_pixels=20):
    player=features.get('player')
    if not player or features.get('combat_present',features.get('enemy_count')):return None
    vx,vy=ContinuousActions.vector(direction);floor=SpatialVision.floor_mask(frame)
    px,py=map(round,player);cv2.circle(floor,(px,py),40,255,-1)
    for entity in list(features.get('entities',[]))+list(extra_obstacles):
        if entity['kind'] not in ('hazard','rock_obstacle_candidate','bomb_candidate','portable_brazier'):continue
        x,y,w,h=entity['bbox'];floor[max(0,y-20):min(900,y+h+25),max(0,x-20):min(1600,x+w+20)]=0
    clearance=cv2.distanceTransform(floor,cv2.DIST_L2,5);safe=0
    for distance in range(10,max_pixels+1,10):
        x,y=round(px+vx*distance),round(py+vy*distance)
        if not 0<=x<1600 or not 0<=y<900 or clearance[y,x]<clearance_pixels:break
        safe=distance
    # Leave a measured 30px cushion; no pulse into map fog using guide prose.
    travel=safe-30
    if travel<60:return None
    return {'direction':[vx,vy],'live_floor_distance_pixels':safe,'desired_travel_pixels':travel,'duration_ms':min(600,travel/.44),'assumed_world_pixels_per_ms':.44,'source':'observed 132px/300ms full-axis calibration','map_frontier_extension':True}
