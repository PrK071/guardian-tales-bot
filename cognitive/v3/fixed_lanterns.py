"""Track one fixed lantern through contact, separation and two confirmations."""
import math,time
import cv2
import numpy as np
from ..contracts import Action,Provenance
from ..puzzle_control import BombRockController,rock_mask
from ..spatial import SpatialVision
from .local_observation import motion_after_pulse

def fixed_base_motion(before,after,heading,duration_ms):
    """Recover camera translation from unambiguous currently seen fixed bases."""
    from ..puzzle_control import DIRECTIONS
    from ..lantern_control import LanternController
    if before.get('scene')!='jogo' or after.get('scene')!='jogo':return None
    def bases(features):
        return [o for o in features.get('puzzle_objects',[]) if o.get('confidence',0)>=.84 and (o['kind']=='standing_lantern_unlit' or o['kind']=='standing_lantern_lit' and o.get('method')=='floor_lantern_pedestal_with_current_fire')]
    vx,vy=DIRECTIONS[heading];hypotheses=[]
    for first in bases(before):
        for second in bases(after):
            a=LanternController.foot(first);b=LanternController.foot(second);shift=[b[i]-a[i] for i in (0,1)]
            if math.hypot(*shift)>duration_ms*.44+40:continue
            if any(shift[i]*(-1 if value>0 else 1)<-12 if value else abs(shift[i])>16 for i,value in enumerate((vx,vy))):continue
            hypotheses.append({'before_bbox':first['bbox'],'after_bbox':second['bbox'],'shift':shift,'confidence':min(first['confidence'],second['confidence'])})
    if not hypotheses or any(math.dist(a['shift'],b['shift'])>12 for a in hypotheses for b in hypotheses):return None
    shift=[float(sum(h['shift'][i] for h in hypotheses)/len(hypotheses)) for i in (0,1)];bp=before.get('player');ap=after.get('player');player=[float(ap[i]-bp[i]) for i in (0,1)] if bp and ap else [0.,0.]
    return {'background_dx':shift[0],'background_dy':shift[1],'confidence':float(min(h['confidence'] for h in hypotheses)),'method':'unambiguous_current_fixed_base_translation','matches':hypotheses,'source_frames':[before['frame'],after['frame']],'player_dx':player[0],'player_dy':player[1],'effective_dx':player[0]-shift[0],'effective_dy':player[1]-shift[1],'moved':bool(math.hypot(player[0]-shift[0],player[1]-shift[1])>8)}

def fire_offset(s,frame,f):
    held=s.lantern_vision.held_match(frame,f['player'])
    if not held:raise RuntimeError('No verified carried brazier for fixed-lantern contact')
    x,y,w,h=held['bbox'];mask=s.lantern_vision.fire_mask(frame)
    y1=max(50,y-100);y2=y+h;x1=max(320,x);x2=min(1400,x+w)
    ys,xs=np.nonzero(mask[y1:y2,x1:x2])
    if len(xs)<450:raise RuntimeError('Carried fire is not currently visible')
    return [float(xs.mean()+x1-f['player'][0]),float(ys.mean()+y1-f['player'][1])]

def light_nearest(s,c,max_actions=16):
    began=time.perf_counter();before,f=c.observe('v3-fixed-lantern-start')
    candidates=c.objects(f,'standing_lantern_unlit')
    if not candidates:raise RuntimeError('No currently visible unlit fixed lantern')
    obj=min(candidates,key=lambda o:math.dist(c.foot(o),f['player']));x,y,w,h=obj['bbox']
    bowl=[x+w/2,y+25];base=c.foot(obj);side=1 if bowl[0]>f['player'][0] else -1;initial=f['frame'];stalled=0;contacts=[]
    for _ in range(max_actions):
        c.check();offset=fire_offset(s,before,f);target=[bowl[i]-offset[i] for i in range(2)]
        if math.dist(f['player'],target)<20:break
        try:heading,ms=BombRockController.local_approach(before,f,target)
        except RuntimeError:
            # Fire can remove the adjacent green rocks. Wait with all controls
            # released, then demand an actual changed obstacle observation.
            prior=int(np.count_nonzero(rock_mask(before)));time.sleep(1.3)
            after,af=c.observe('v3-fixed-rock-burn-wait');motion=SpatialVision.motion(before,after,f['player'],af['player'])
            bowl=[bowl[0]+motion['background_dx'],bowl[1]+motion['background_dy']];base=[base[0]+motion['background_dx'],base[1]+motion['background_dy']]
            changed=int(np.count_nonzero(rock_mask(after)))<prior*.85
            if not changed:raise RuntimeError('Fixed-lantern approach is blocked without verified rock removal')
            before,f=after,af;continue
        row=s.pulse(Action('move',{'direction':heading,'ms':ms},'Align verified carried flame with the tracked fixed lantern'))
        after,af,motion=motion_after_pulse(s,c,row,before,f,'v3-fixed-contact-progress')
        if motion['confidence']<.25:
            recovered=fixed_base_motion(f,af,heading,ms)
            if recovered:motion=recovered
            else:
                if hasattr(s,'failure_checkpoint'):
                    s.failure_checkpoint('Fixed-lantern alignment: before pair',before,f);s.failure_checkpoint('Fixed-lantern alignment: after pair',after,af)
                raise RuntimeError('Fixed-lantern target tracking lost camera alignment')
        bowl=[bowl[0]+motion['background_dx'],bowl[1]+motion['background_dy']];base=[base[0]+motion['background_dx'],base[1]+motion['background_dy']]
        contacts.append({'frame':af['frame'],'motion':motion,'control':row['metrics']['continuous_control']})
        stalled=stalled+1 if math.hypot(motion['effective_dx'],motion['effective_dy'])<8 else 0
        before,f=after,af
        near_lit=[o for o in c.objects(f,'standing_lantern_lit') if math.dist(c.foot(o),base)<85]
        # A weak/occluded unlit template plus the carried flame entering this
        # region is not contact. Keep approaching its tracked geometry until
        # aligned, or until an actual floor pedestal has observed fixed fire.
        if near_lit:break
        if stalled>=2:raise RuntimeError('Fixed-lantern contact stalled twice')
    else:raise RuntimeError('Fixed-lantern contact action budget exhausted')
    return separate_and_verify(s,c,before,f,bowl,base,side,initial,contacts,began)

def verify_fixed_from_source(s,c,source):
    import json
    from ..map_navigation import PauseMap
    folder=(s.root/'data/v3'/source).resolve()
    if folder.parent!=(s.root/'data/v3').resolve():raise RuntimeError('Contact source outside project data/v3')
    files=list(folder.glob('*fixed-lantern-start.jpg'));maps=sorted(folder.glob('*after-pausa.jpg'))
    if len(files)!=1 or not maps:raise RuntimeError('Interrupted contact source lacks game/map evidence')
    original=cv2.imread(str(files[0]));objects=c.objects({'puzzle_objects':s.lantern_vision.detect(original,[800.5,445],True)},'standing_lantern_unlit')
    if len(objects)!=1:raise RuntimeError('Interrupted contact has an ambiguous unlit target')
    report=json.loads((folder/'report.json').read_text());moves=[r for r in report['actions'] if r['action']['op']=='move']
    if not moves or any(r['metrics']['motion']['confidence']<.25 for r in moves):raise RuntimeError('Interrupted contact has an unverified motion interval')
    shift=[sum(r['metrics']['motion'][key] for r in moves) for key in ('background_dx','background_dy')]
    base=[c.foot(objects[0])[i]+shift[i] for i in range(2)];actor=moves[-1]['after']['player']
    state=PauseMap().parse(cv2.imread(str(maps[-1])));alignment=s.map_anchor.locate(state)
    if not actor or not alignment:raise RuntimeError('Interrupted contact pose unavailable')
    position=s.map_anchor.project(state['player'],alignment);ratio=.44/s.speeds['move'];fixed=[position[i]+(base[i]-actor[i])/ratio for i in range(2)]
    return verify_fixed_at_reference(s,c,fixed,str(files[0].relative_to(s.root)),[],time.perf_counter())

def separate_and_verify(s,c,before,f,bowl,base,side,initial,contacts,began):
    _,_,actor_reference,_=s.map_state('v3-fixed-verification-map');ratio=.44/s.speeds['move']
    fixed=[actor_reference[i]+(base[i]-f['player'][i])/ratio for i in range(2)]
    return verify_fixed_at_reference(s,c,fixed,initial,contacts,began)

def verify_fixed_at_reference(s,c,fixed,initial,contacts,began):
    from .room_navigation import goto_room_checkpoint
    viewpoint=[426,775 if fixed[1]>735 else 713];goto_room_checkpoint(s,viewpoint)
    _,_,actor_reference,map_features=s.map_state('v3-fixed-independent-view-map');s.transition('jogo');before,f=c.observe('v3-fixed-separated-viewpoint')
    ratio=.44/s.speeds['move'];base=[f['player'][i]+(fixed[i]-actor_reference[i])*ratio for i in range(2)]
    confirmations=[];checks=[]
    for _ in range(3):
        after,af=c.observe('v3-fixed-independent-check');motion=SpatialVision.motion(before,after,f['player'],af['player'])
        shifted=[base[0]+motion['background_dx'],base[1]+motion['background_dy']]
        lit=[o for o in c.objects(af,'standing_lantern_lit') if math.dist(c.foot(o),shifted)<85]
        unlit=[o for o in c.objects(af,'standing_lantern_unlit') if math.dist(c.foot(o),shifted)<85]
        valid=bool(motion['confidence']>=.25 and lit and not unlit and math.dist(af['player'],lit[0]['fire_center'])>300)
        checks.append({'frame':af['frame'],'valid':valid,'expected_base':shifted,'lit':lit,'unlit':unlit,'motion':motion})
        if valid:confirmations.append(af['frame'])
        else:confirmations=[]
        if len(confirmations)>=2:break
        time.sleep(.1)
    result={'verified':len(confirmations)>=2,'initial_frame':initial,'confirmations':confirmations,'frame':af['frame'],'contacts':contacts,'checks':checks,'viewpoint_reference':viewpoint,'fixed_base_reference':fixed,'map_frame':map_features['frame'],'seconds':time.perf_counter()-began,'stage_complete':False}
    s.memory.remember('episodic','v3_fixed_lantern',s.scope,{'run_id':s.run_id,**result},Provenance(af['frame'],method='tracked_contact_registered_to_map_then_two_separated_fixed_fire_observations'),.95,'verified' if result['verified'] else 'uncertain')
    if not result['verified']:raise RuntimeError('Persistent fixed fire was not independently confirmed at its registered room location')
    return result
