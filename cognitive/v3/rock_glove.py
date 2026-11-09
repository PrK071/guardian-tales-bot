"""Use the observed Mole Glove affordance, verifying current rock removal."""
import math,time
import cv2
import numpy as np
from ..contracts import Action,Provenance
from ..stage_v2 import InteractionVision
from ..puzzle_control import rock_mask
from ..spatial import SpatialVision

def glove_visible(s,frame):
    template=cv2.imread(str(s.root/'assets/v3/mole_glove.png'))
    if template is None:return False
    mask=cv2.inRange(template,(205,205,205),(255,255,255))
    return float(cv2.matchTemplate(InteractionVision.mask(frame),mask,cv2.TM_CCOEFF_NORMED)[0,0])>.92

def registered_column_goal(actor_reference,objects,known,rock,ratio,raw_player):
    """Locate a stone's side using a currently seen, previously mapped lamp."""
    from ..lantern_control import LanternController
    matches=[]
    for row in known:
        reference=row['content'].get('fixed_base_reference')
        if row['validation']!='verified' or not reference or len(reference)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in reference):continue
        for obj in objects:
            if obj['kind'] not in ('standing_lantern_unlit','standing_lantern_lit'):continue
            if obj['kind']=='standing_lantern_lit' and obj.get('method')!='floor_lantern_pedestal_with_current_fire':continue
            point=LanternController.foot(obj)
            actor_pixel=[point[i]-(reference[i]-actor_reference[i])*ratio for i in range(2)]
            if math.dist(actor_pixel,[800,445])>50 or raw_player and math.dist(actor_pixel,raw_player)>80:continue
            matches.append((obj['confidence'],row,reference,point,actor_pixel))
    if not matches:raise RuntimeError('No unambiguous registered fixed lamp for a stone-side approach')
    if any(math.dist(a[4],b[4])>35 for a in matches for b in matches):raise RuntimeError('Registered lamp observations disagree on room geometry')
    _,row,reference,point,actor_pixel=max(matches,key=lambda value:value[0]);x,y,w,h=rock['bbox']
    low=[reference[0]+(x-point[0])/ratio,reference[1]+(y-point[1])/ratio];high=[low[0]+w/ratio,low[1]+h/ratio]
    cy=min(max(actor_reference[1],low[1]+6),high[1]-6) if high[1]-low[1]>=12 else (low[1]+high[1])/2
    candidates=[{'target':[low[0]-gap,cy],'face':'right','standoff_reference':gap} for gap in (6,10,14,18)]+[{'target':[high[0]+gap,cy],'face':'left','standoff_reference':gap} for gap in (6,10,14,18)]
    # Prefer the closest safe standoff to the observed stone. A map edge
    # can exclude its apparent pixel-side margin; retain the clearance gate.
    candidates.sort(key=lambda candidate:(candidate['standoff_reference'],math.dist(candidate['target'],actor_reference)))
    return {'candidates':candidates,'landmark_memory':row['id'],'landmark_reference':reference,'observed_landmark_foot':point,'associated_actor_pixel':actor_pixel,'rock_reference_bounds':[low,high]}

def approach_registered_column(s,c,frame,features,rock):
    """Fallback when the local mask cannot approach a wall-adjacent stone."""
    if not hasattr(s,'map_state') or s.backend.held:raise RuntimeError('Registered tool approach requires released controls and a verified map')
    source=features['frame'];objects=features.get('puzzle_objects',[])
    state,alignment,position,map_features=s.map_state('v3-registered-stone-map')
    known=s.memory.retrieve(s.scope,kind='v3_fixed_lantern',include_global=False,limit=30)
    geometry=registered_column_goal(position,objects,known,rock,.44/s.speeds['move'],features.get('player'))
    clearance=cv2.distanceTransform(state['floor'],cv2.DIST_L2,5);chosen=None
    for candidate in geometry['candidates']:
        raw=s.raw_target(candidate['target'],alignment);x,y=map(round,raw)
        if 0<=x<1600 and 0<=y<900 and clearance[y,x]>12*alignment['scale'] and math.dist(position,candidate['target'])<140:chosen=candidate;break
    if not chosen:raise RuntimeError('No registered stone side has observed static floor clearance')
    checkpoint=(state,alignment,position,map_features,len(s.controls.actions));s.transition('jogo');results=[]
    for attempt in range(3):
        result=s.navigate_to(chosen['target'],tolerance=4,allow_npc_bypass=True,_checkpoint=checkpoint if attempt==0 else None);results.append(result)
        if result.get('reason')=='enemy_detected':s.transition('jogo');raise RuntimeError('Encounter interrupts registered stone approach')
        if result.get('verified'):break
        if not result.get('progress_verified'):raise RuntimeError('Registered stone-side route did not progress')
    else:raise RuntimeError('Registered stone-side approach budget exhausted')
    s.transition('jogo');frame,features=c.observe('v3-registered-stone-side')
    if not glove_visible(s,frame):
        s.pulse(Action('move',{'direction':chosen['face'],'ms':80},'Face the observed cracked stone from its verified side checkpoint'))
        frame,features=c.observe('v3-registered-stone-facing')
    if not glove_visible(s,frame):raise RuntimeError('Mole Glove affordance absent at the registered stone side')
    evidence={'verified':True,'source_frame':source,'frame':features['frame'],'map_frame':map_features['frame'],'geometry':geometry,'chosen':chosen,'routes':results}
    s.memory.remember('episodic','v3_registered_stone_approach',s.scope,{'run_id':s.run_id,**evidence},Provenance(features['frame'],method='observed_fixed_lamp_and_independent_map_then_verified_stone_side_and_tool_glyph'),.9,'verified')
    result=drill_visible(s);result['registered_approach']=evidence;return result

def escape_cleared_tile(s):
    """Step into the just-removed tile when sprites occlude a narrow pocket."""
    from ..puzzle_control import direction
    s.transition('jogo');current,f=s.capture('v3-cleared-tile-escape-preflight')
    rows=s.memory.retrieve(s.scope,kind='v3_mole_glove',include_global=False,limit=4)
    rows=[r for r in rows if r['validation']=='verified' and r['content'].get('verified')]
    if not rows:raise RuntimeError('No verified removed tile for bounded escape')
    proof=rows[0]['content'];path=(s.root/proof['before_frame']).resolve()
    if not path.is_relative_to(s.root.resolve()):raise RuntimeError('Removed-tile evidence outside project')
    before=cv2.imread(str(path));motion=SpatialVision.motion(before,current,None,None)
    if motion['confidence']<.25 or not f.get('player'):raise RuntimeError('Removed tile cannot be aligned to current actor')
    x,y,w,h=proof['tile_bbox'];x+=motion['background_dx'];y+=motion['background_dy'];target=[x+w/2,y+h/2];actor=f['player']
    if not (x<=actor[0]<=x+w and y<=actor[1]<=y+h and math.dist(actor,target)<90):raise RuntimeError('Actor is outside the verified cleared tile; no guessed escape')
    for e in f['entities']:
        if e['kind'] not in ('rock_obstacle_candidate','hazard'):continue
        ex,ey,ew,eh=e['bbox']
        if ex-28<target[0]<ex+ew+28 and ey-28<target[1]<ey+eh+28:raise RuntimeError('New obstacle occupies the cleared-tile escape')
    if s.preflight_enemy(f):raise RuntimeError('Encounter interrupts cleared-tile escape')
    ms=max(80,min(200,round(math.dist(actor,target)/.44*.9)))
    row=s.pulse(Action('move',{'direction':direction(target[0]-actor[0],target[1]-actor[1]),'ms':ms},'Step into the independently verified removed stone tile'))
    result={'verified':row['metrics']['motion']['moved'],'frame':s.last_features['frame'],'removed_tile_memory':rows[0]['id'],'motion':row['metrics']['motion']}
    s.memory.remember('episodic','v3_cleared_tile_escape',s.scope,result,Provenance(result['frame'],method='bounded_move_inside_verified_removed_tile'),.9,'verified' if result['verified'] else 'uncertain')
    return result

def drill_visible(s,max_actions=3):
    s.transition('jogo');frame,f=s.capture('v3-glove-preflight');results=[]
    for _ in range(max_actions):
        s.check_cancel()
        if not glove_visible(s,frame):
            if results:break
            raise RuntimeError('Mole Glove affordance not currently observed')
        if s.preflight_enemy(f):raise RuntimeError('Encounter interrupts rock removal')
        rocks=[e for e in f['entities'] if e['kind']=='rock_obstacle_candidate']
        if not rocks or not f.get('player'):raise RuntimeError('No current rock target for glove')
        target=min(rocks,key=lambda e:math.dist(f['player'],[min(max(f['player'][0],e['bbox'][0]),e['bbox'][0]+e['bbox'][2]),min(max(f['player'][1],e['bbox'][1]),e['bbox'][1]+e['bbox'][3])]));x,y,w,h=target['bbox']
        height=min(130,h);y=y if f['player'][1]<y+h/2 else y+h-height;h=height
        # Select the visible cracked tile nearest the player within a group.
        width=min(110,w);left=round(min(max(f['player'][0]-width/2,x),x+w-width));box=[left,y,width,h]
        old=rock_mask(frame);mask=np.zeros_like(old);mask[y:y+h,left:left+width]=old[y:y+h,left:left+width]
        count=int(np.count_nonzero(mask));before=frame.copy();bp=f['player'];source=f['frame']
        if count<4000:raise RuntimeError('Selected cracked tile has insufficient observed rock pixels')
        row=s.pulse(Action('interact',{'ms':900},'Use the observed Mole Glove on the adjacent cracked stone'))
        time.sleep(.25);after,af=s.capture('v3-glove-removal-check');motion=SpatialVision.motion(before,after,bp,af.get('player'))
        shift=np.float32([[1,0,motion['background_dx']],[0,1,motion['background_dy']]])
        aligned=cv2.warpAffine(mask,shift,(1600,900))>0;remaining=int(np.count_nonzero((rock_mask(after)>0)&aligned));floor=SpatialVision.floor_mask(after)>0
        raw_exposed=float(np.mean(floor[aligned])) if np.any(aligned) else 0
        visible=aligned.copy();occlusions=[]
        for entity in af.get('entities',[]):
            if entity['kind']!='player':continue
            ax,ay,aw,ah=map(round,entity['bbox']);visible[max(0,ay):min(900,ay+ah),max(0,ax):min(1600,ax+aw)]=False;occlusions.append(entity['bbox'])
        visible_fraction=float(np.count_nonzero(visible)/np.count_nonzero(aligned)) if np.any(aligned) else 0
        exposed=float(np.mean(floor[visible])) if np.any(visible) else 0
        verified=bool(motion['confidence']>=.25 and remaining<count*.25 and visible_fraction>=.30 and exposed>.55)
        result={'verified':verified,'before_frame':source,'frame':af['frame'],'rock_pixels_before':count,'rock_pixels_remaining':remaining,'exposed_floor_fraction':exposed,'raw_exposed_floor_fraction':raw_exposed,'visible_tile_fraction':visible_fraction,'observed_actor_occlusions':occlusions,'tile_bbox':box,'motion':motion};results.append(result)
        s.memory.remember('episodic','v3_mole_glove',s.scope,{'run_id':s.run_id,**result},Provenance(af['frame'],method='observed_tool_glyph_then_aligned_cracked_tile_removal_and_exposed_floor'),.95,'verified' if verified else 'uncertain')
        if row['metrics'].get('operation_id'):s.memory.operation(row['metrics']['operation_id'],'observed' if verified else 'uncertain',s.observation(af).id,result)
        if not verified:raise RuntimeError('Mole Glove input did not produce verified tile removal')
        frame,f=after,af
    return {'verified':bool(results) and all(r['verified'] for r in results),'tiles':results,'frame':f['frame'],'stage_complete':False}


def ensure_lantern_access(s,c,obj,max_steps=12):
    """Clear the cracked tile in the lantern column before carrying fire."""
    from .carry_combat import arrow_visible
    from ..puzzle_control import BombRockController,direction
    frame,f=c.observe('v3-glove-access-start');lamp=c.foot(obj)
    def relevant(features,point):
        return [e for e in features['entities'] if e['kind']=='rock_obstacle_candidate' and e['bbox'][0]-28<point[0]<e['bbox'][0]+e['bbox'][2]+28 and abs(e['bbox'][1]+e['bbox'][3]/2-point[1])<250]
    if not relevant(f,lamp):return {'verified':True,'already_accessible':True}
    if arrow_visible(s,frame):
        side=-1 if lamp[0]>f['player'][0] else 1
        heading,ms=BombRockController.local_approach(frame,f,[f['player'][0]+side*120,f['player'][1]])
        s.pulse(Action('move',{'direction':heading,'ms':min(ms,100)},'Face clear room floor to free the Mole Glove control'))
        after,af=c.observe('v3-glove-before-release');motion=SpatialVision.motion(frame,after,f['player'],af['player']);lamp=[lamp[0]+motion['background_dx'],lamp[1]+motion['background_dy']];frame,f=after,af
        row=s.pulse(Action('interact',{'ms':100},'Release verified carried torch for the Mole Glove prerequisite'));s.held_object_kind=None
        frame,f=s.capture('v3-glove-released')
        if arrow_visible(s,frame):raise RuntimeError('Torch release not observed; glove input withheld')
        if row['metrics'].get('operation_id'):s.memory.operation(row['metrics']['operation_id'],'observed',s.observation(f).id,{'item_release_verified':True,'frame':f['frame']})
    stalled=0
    for _ in range(max_steps):
        c.check()
        if glove_visible(s,frame):return drill_visible(s)
        rocks=relevant(f,lamp)
        if not rocks:return {'verified':True,'current_column_clear':True,'frame':f['frame']}
        rock=min(rocks,key=lambda e:abs(e['bbox'][1]+e['bbox'][3]/2-f['player'][1]));x,y,w,h=rock['bbox']
        approach=[lamp[0],y-40 if f['player'][1]<y+h/2 else y+h+40]
        if math.dist(f['player'],approach)<70:heading=direction(lamp[0]-f['player'][0],y+h/2-f['player'][1]);ms=100
        else:
            try:heading,ms=BombRockController.local_approach(frame,f,approach)
            except RuntimeError:return approach_registered_column(s,c,frame,f,rock)
        s.pulse(Action('move',{'direction':heading,'ms':ms},'Approach cracked stone until the observed Mole Glove affordance appears'))
        after,af=c.observe('v3-glove-access-progress');motion=SpatialVision.motion(frame,after,f['player'],af['player'])
        if motion['confidence']<.25:raise RuntimeError('Lost observed rock/lantern alignment')
        lamp=[lamp[0]+motion['background_dx'],lamp[1]+motion['background_dy']];frame,f=after,af
        stalled=0 if motion['moved'] else stalled+1
        if stalled>=2 and not glove_visible(s,frame):raise RuntimeError('Cracked tile approach stalled without tool affordance')
    raise RuntimeError('Mole Glove prerequisite approach budget exhausted')
