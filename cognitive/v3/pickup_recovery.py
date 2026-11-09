"""Reconcile one interrupted pickup using its original before/after evidence."""
import json,math
import cv2
from ..contracts import Action,Provenance
from ..spatial import SpatialVision
from ..stage_v2 import InteractionVision
from .exploration import visible_floor_horizon

def recover_pickup(s,source):
    path=(s.root/source).resolve()
    if not path.is_relative_to((s.root/'data/v3').resolve()):raise RuntimeError('Pickup evidence outside project data')
    report=json.loads(path.read_text());events=report.get('events',[])
    prior=next(e for e in events if e['phase']=='pickup_affordance');transfer=next(e for e in events if e['phase']=='pickup_transfer')
    if transfer.get('verified') or transfer.get('ground_score',1)>=.75 or any(a['action']['op']=='move' for a in report.get('actions',[])):raise RuntimeError('Source is not an interrupted stationary transfer')
    entries=s.memory.retrieve(s.scope,kind='v2_prepared_spawn',include_global=False,limit=1)
    if entries and prior['at']<entries[0]['content']['prepared_at']:raise RuntimeError('Pickup belongs to an earlier stage entry')
    before=cv2.imread(str(s.root/prior['frame']));reference=cv2.imread(str(s.root/transfer['frame']))
    if before is None or reference is None:raise RuntimeError('Missing transfer evidence')
    s.transition('jogo');frame,f=s.capture('v3-pickup-recovery-current')
    motion=SpatialVision.motion(before,frame,prior['player'],f['player']);expected=[prior['player'][0]+motion['background_dx'],prior['player'][1]+motion['background_dy']]
    held=s.lantern_vision.held_match(frame,expected)
    glyph=float(cv2.matchTemplate(InteractionVision.mask(frame),InteractionVision.mask(reference),cv2.TM_CCOEFF_NORMED)[0,0])
    if f['scene']!='jogo' or motion['confidence']<.25 or not held or held['confidence']<.70 or glyph<.92:raise RuntimeError('Current scene does not reconcile the interrupted transfer')
    x,y,w,h=held['bbox'];s.held_pose_offset=[(expected[0]-x-w/2)/w,(expected[1]-y)/h];s.held_actor=expected;s.held_object_kind='brazier';s.vision.last_player=tuple(expected)
    frame,f=s.capture('v3-pickup-recovery-calibrated')
    horizon=visible_floor_horizon(frame,f,'left',max_pixels=140)
    if not horizon or horizon['desired_travel_pixels']<70:raise RuntimeError('No observed clear floor for held-object follow verification')
    row=s.pulse(Action('move',{'direction':'left','ms':160},'Verify the reconciled brazier follows the actor on observed floor'))
    frame,f=s.capture('v3-recovered-held-follow');held=s.lantern_vision.held_match(frame,f['player'])
    if not row['metrics']['motion']['moved'] or not held or held['confidence']<.70:raise RuntimeError('Reconciled object did not follow the observed movement')
    result={'verified':True,'run_id':s.run_id,'frame':f['frame'],'held_match':held,'held_pose_offset':s.held_pose_offset,'source_interrupted_transfer':str(path.relative_to(s.root)),'stage_complete':False}
    s.memory.remember('working','v2_held_brazier',s.scope,result,Provenance(f['frame'],method='interrupted_ground_transfer_then_current_throw_glyph_and_verified_actor_follow'),.95,'verified',dedupe='v2:held-brazier:'+s.scope)
    return result
