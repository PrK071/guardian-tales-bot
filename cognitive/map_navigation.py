"""Small BFS over the currently visible pause map; no global SLAM/map assumption."""
from collections import deque
import math
import cv2
import numpy as np

class PauseMap:
    def parse(self,frame):
        h,w=frame.shape[:2];hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        floor=cv2.inRange(hsv,(30,75,70),(85,255,240));floor[:150]=0;floor[760:]=0;floor[:,:380]=0;floor[:,1350:]=0
        raw_floor=floor.copy()
        count,labels,stats,_=cv2.connectedComponentsWithStats(floor)
        if count<2:raise ValueError('No observed floor component in the pause map')
        index=1+int(np.argmax(stats[1:,cv2.CC_STAT_AREA]));floor=(labels==index).astype(np.uint8)*255
        x,y,bw,bh=map(int,stats[index,:4])
        red=cv2.inRange(hsv,(0,160,170),(8,255,255))|cv2.inRange(hsv,(172,160,170),(180,255,255))
        red[:150]=0;red[760:]=0;red[:,:380]=0;red[:,1350:]=0
        contours,_=cv2.findContours(red,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);pins=[]
        for contour in contours:
            px,py,pw,ph=cv2.boundingRect(contour)
            if 18<=pw<=50 and 22<=ph<=65 and cv2.contourArea(contour)>250 and x-30<px<x+bw+30 and y-40<py<y+bh:
                pins.append((px+pw/2,py+ph-1))
        if len(pins)!=1:raise ValueError('Map player marker absent or ambiguous')
        player=pins[0]
        marker_bbox=None
        # Keep small pieces below the opaque pin until reconstructing its
        # occlusion; choosing the largest component first can discard that
        # observed support in a narrow stem, especially after JPEG compression.
        floor=raw_floor
        # The opaque location pin can cover the whole narrow corridor. Restore
        # only rows under that observed icon with green floor on both sides.
        for contour in contours:
            px,py,pw,ph=cv2.boundingRect(contour)
            if abs(px+pw/2-player[0])<1 and py+ph-1==player[1]:
                marker_bbox=[px-4,py-4,pw+8,ph+8]
                left=max(0,px-5);right=min(w-1,px+pw+5)
                for row in range(py,min(h,py+ph+4)):
                    if np.any(floor[row,max(0,left-5):left]) and np.any(floor[row,right:min(w,right+5)]):floor[row,left:right+1]=255
                top=max(0,py-5);bottom=min(h-1,py+ph+5)
                for column in range(px,min(w,px+pw)):
                    if np.any(floor[max(0,top-5):top,column]) and np.any(floor[bottom:min(h,bottom+5),column]):floor[top:bottom+1,column]=255
        count,labels,stats,_=cv2.connectedComponentsWithStats(floor)
        index=1+int(np.argmax(stats[1:,cv2.CC_STAT_AREA]));floor=(labels==index).astype(np.uint8)*255
        x,y,bw,bh=map(int,stats[index,:4])
        # Fill enclosed icon holes, without joining separate corridors across walls.
        inv=255-floor;flood=inv.copy();cv2.floodFill(flood,None,(0,0),128)
        holes=(flood==255);floor[holes]=255
        contours,_=cv2.findContours(floor,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
        contour=max(contours,key=cv2.contourArea).reshape(-1,2)
        white=cv2.inRange(hsv,(0,0,205),(180,85,255))
        missing=[]
        for px,py in contour:
            patch=white[max(0,py-6):py+7,max(0,px-6):px+7]
            missing.append(np.count_nonzero(patch)==0 and math.dist((px,py),player)>35)
        groups=[];group=[]
        for i,flag in enumerate(missing+missing[:1]):
            if flag:group.append(contour[i%len(contour)].tolist())
            elif group:
                if len(group)>=12:groups.append(group)
                group=[]
        if group and len(group)>=12:groups.append(group)
        frontiers=[]
        for group in groups:
            points=np.array(group);mid=np.median(points,axis=0);spread=np.ptp(points,axis=0)
            if max(spread)<15:continue
            point=[float(mid[0]),float(mid[1])]
            frontiers.append({'point':point,'visible_gap_pixels':len(group),'confidence':.8,'kind':'unwalled_observed_map_boundary'})
        return {'player':list(player),'player_marker_bbox':marker_bbox,'bbox':[x,y,bw,bh],'frontiers':frontiers,'floor':floor,'confidence':.9}
    def path(self,map_state,target,cell=None,margin=None,strict_centers=False,reachable_target=False):
        mask=map_state['floor'];height,width=mask.shape
        scale=map_state.get('map_scale',1.)
        cell=cell if cell is not None else max(2,round(4*scale))
        margin=margin if margin is not None else 12*scale
        # A visible floor pixel is not sufficient clearance for the character.
        # Keep a 12-map-pixel margin from walls before finding a local route.
        clearance=cv2.distanceTransform(mask,cv2.DIST_L2,5)>margin
        # Four-pixel cells preserve a narrow valid center strip after wall
        # clearance; an eight-pixel grid can alias it into disconnected islands.
        if strict_centers:
            xs=np.rint(np.arange(width//cell)*cell+cell/2).astype(int);ys=np.rint(np.arange(height//cell)*cell+cell/2).astype(int)
            grid=clearance[np.minimum(ys,height-1)[:,None],np.minimum(xs,width-1)[None,:]]
        else:grid=cv2.resize(clearance.astype(np.uint8)*255,(width//cell,height//cell),interpolation=cv2.INTER_AREA)>100
        cells=np.argwhere(grid)
        if not len(cells):raise ValueError('No observed floor node with required player clearance')
        def nearest(point):return tuple(cells[np.argmin(np.linalg.norm(cells-np.array([point[1]/cell,point[0]/cell]),axis=1))])
        start=nearest(map_state['player'])
        if reachable_target:
            _,labels=cv2.connectedComponents(grid.astype(np.uint8),connectivity=4)
            cells=np.argwhere(labels==labels[start])
        end=nearest(target);queue=deque([start]);parents={start:None}
        while queue:
            current=queue.popleft()
            if current==end:break
            directions=sorted(((-1,0),(1,0),(0,-1),(0,1)),key=lambda d:abs(current[0]+d[0]-end[0])+abs(current[1]+d[1]-end[1]))
            # Tie-break toward the largest remaining axis to avoid changing lanes
            # prematurely in a wide room on every newly revealed map image.
            if abs(current[1]-end[1])>abs(current[0]-end[0]):directions.sort(key=lambda d:(abs(current[0]+d[0]-end[0])+abs(current[1]+d[1]-end[1]),d[1]==0))
            for dy,dx in directions:
                node=(current[0]+dy,current[1]+dx)
                if 0<=node[0]<grid.shape[0] and 0<=node[1]<grid.shape[1] and grid[node] and node not in parents:parents[node]=current;queue.append(node)
        if end not in parents:raise ValueError('No path through the observed map floor')
        route=[];current=end
        while current is not None:route.append([current[1]*cell+cell/2,current[0]*cell+cell/2]);current=parents[current]
        route.reverse();return route
    def next_motion(self,map_state,target):
        path=self.path(map_state,target)
        if len(path)<2:return None
        # First cardinal run only, reobserve after the pulse rather than assuming the entire route.
        dx=path[1][0]-path[0][0];dy=path[1][1]-path[0][1];last=path[1]
        for point in path[2:]:
            if (point[0]-last[0],point[1]-last[1])!=(dx,dy):break
            last=point
        distance=math.dist(path[0],last)
        direction='right' if dx>0 else 'left' if dx<0 else 'down' if dy>0 else 'up'
        normalized=distance/map_state.get('map_scale',1.)
        return {'direction':direction,'ms':300 if normalized<20 else 600 if normalized<60 else 900,'map_distance':round(distance,2),'reference_distance':round(normalized,2),'path':path,'target':target}
    def exploration_plan(self,map_state):
        plans=[]
        for frontier in map_state.get('frontiers',[]):
            try:plan=self.next_motion(map_state,frontier['point'])
            except ValueError:continue
            # A marker-occluded sliver may snap to the same clear floor cell as
            # the player. It offers no executable displacement or exploration.
            if plan:plans.append(plan)
        if not plans:raise ValueError('No reachable observable frontier with a nonzero path')
        return min(plans,key=lambda plan:len(plan['path']))
    def recovery(self,map_state,failed_direction):
        """One short side step, only through floor with measured wall clearance."""
        px,py=map_state['player'];distance=cv2.distanceTransform(map_state['floor'],cv2.DIST_L2,5);scale=map_state.get('map_scale',1.)
        options=((0,-1,'up'),(0,1,'down')) if failed_direction in ('left','right') else ((-1,0,'left'),(1,0,'right'))
        candidates=[]
        for dx,dy,direction in options:
            points=[(int(px+dx*s*scale),int(py+dy*s*scale)) for s in (8,16,24)]
            if all(0<=x<distance.shape[1] and 0<=y<distance.shape[0] and distance[y,x]>12*scale for x,y in points):
                candidates.append((float(distance[points[-1][1],points[-1][0]]),direction))
        if not candidates:return None
        return {'direction':max(candidates)[1],'ms':300,'strategy':'observed_clear_perpendicular_step','failed_direction':failed_direction}
