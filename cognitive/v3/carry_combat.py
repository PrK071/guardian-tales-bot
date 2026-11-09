"""Release a visually confirmed carried item before using normal combat."""
import cv2,time
from ..contracts import Action,Provenance
from ..stage_v2 import InteractionVision
from ..lantern_control import LanternController

def arrow_visible(s,frame):
    template=cv2.imread(str(s.root/'assets/v3/throw_arrow.png'))
    if template is None:return False
    mask=cv2.inRange(template,(205,205,205),(255,255,255))
    return float(cv2.matchTemplate(InteractionVision.mask(frame),mask,cv2.TM_CCOEFF_NORMED)[0,0])>.92

def fight_with_carried_item(s,seconds=45,recover_item=True,prior_enemy_evidence=None):
    s.transition('jogo');frame,f=s.capture('v3-carry-combat-preflight');released=False
    if arrow_visible(s,frame) and s.held_object_kind!='brazier':
        frame,f=LanternController(s).restore_held()
    current_confirmed=bool(f.get('combat_present',f['enemy_count']) and s.preflight_enemy(f))
    prior_valid=bool(prior_enemy_evidence and prior_enemy_evidence.get('scene')=='jogo' and prior_enemy_evidence.get('combat_present',prior_enemy_evidence.get('enemy_count')) and 0<=time.time()-prior_enemy_evidence.get('at',0)<10)
    if current_confirmed:prior_enemy_evidence=dict(s.last_features)
    elif not prior_valid:raise RuntimeError('No confirmed current encounter to handle')
    if arrow_visible(s,frame):
        known=s.memory.retrieve(s.scope,kind='v2_held_brazier',include_global=False,limit=1)
        held=s.lantern_vision.held_match(frame,f.get('player'))
        if not known or known[0]['validation']!='verified' or not held or held['confidence']<.70:raise RuntimeError('Carried item identity not reconciled before combat')
        row=s.pulse(Action('interact',{'ms':100},'Release the verified carried brazier before normal combat'))
        s.held_object_kind=None
        for _ in range(5):
            frame,f=s.capture('v3-item-release-check')
            if not arrow_visible(s,frame):released=True;break
            time.sleep(.08)
        if not released:raise RuntimeError('Item release not observed; no repeated throw')
        if row['metrics'].get('operation_id'):s.memory.operation(row['metrics']['operation_id'],'observed',s.observation(f).id,{'item_release_verified':True,'frame':f['frame']})
    result=s.fight_continuously(seconds,prior_enemy_evidence=prior_enemy_evidence);result['carried_item_released']=released;result['prior_encounter_frame']=prior_enemy_evidence['frame']
    if result['visible_combat_ended'] and released and recover_item:
        s.transition('jogo');frame,f=s.capture('v3-recover-released-item')
        if any(o['kind']=='portable_brazier' for o in f.get('puzzle_objects',[])):
            try:result['item_reacquired']=LanternController(s,seconds=90).pickup()
            except RuntimeError as exc:result['item_reacquired']={'verified':False,'reason':str(exc),'frame':s.last_features['frame']}
        else:result['item_reacquired']={'verified':False,'reason':'released brazier not currently visible','frame':f['frame']}
        s.transition('pausa')
    return result
