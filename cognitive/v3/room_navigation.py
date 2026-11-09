"""Local gameplay-floor fallback for a compact object room, with map checks."""
import math,time
from ..contracts import Action,Provenance
from ..puzzle_control import BombRockController

def goto_room_checkpoint(s,target,tolerance=7):
    """Reuse long mapped segments, falling back only at the tight room edge."""
    def local():
        try:return navigate_room(s,target,tolerance)
        except RuntimeError as exc:
            if str(exc)!='No direct local segment with observed player clearance':raise
            from .rock_glove import escape_cleared_tile
            # A glove lunge can leave the actor at a sprite-occluded corner.
            # Existing escape requires alignment to a verified removed tile,
            # the actor inside it and no current rock/hazard at the endpoint.
            result=escape_cleared_tile(s)
            if not result['verified']:raise RuntimeError('Removed-tile room escape did not move')
            return navigate_room(s,target,tolerance)
    for _ in range(5):
        try:
            result=s.navigate_to(target,tolerance=tolerance,allow_npc_bypass=True)
        except ValueError:
            return local()
        if result.get('verified'):return result
        if result.get('reason')=='enemy_detected':raise RuntimeError('Combat interrupts room checkpoint')
        if not result.get('progress_verified'):return local()
    raise RuntimeError('Room checkpoint segment budget exhausted')

def navigate_room(s,target,tolerance=7,max_actions=16):
    began=time.perf_counter();_,_,position,initial=s.map_state('v3-room-before-map');ratio=.44/s.speeds['move'];initial_error=math.dist(position,target)
    if initial_error>140:raise RuntimeError('Local room target is beyond the bounded observation horizon')
    last_error=initial_error;controls=[];goal_pixel=None
    for index in range(max_actions+1):
        s.check_cancel()
        if math.dist(position,target)<=tolerance:
            result={'verified':True,'before_frame':initial['frame'],'after_frame':s.last_features['frame'],'after':position,'target':target,'goal_error_reference_pixels':math.dist(position,target),'seconds':time.perf_counter()-began,'actions':controls,'model_calls':0}
            s.memory.remember('episodic','v3_room_navigation',s.scope,{'run_id':s.run_id,**result},Provenance(s.last_features['frame'],method='visible_gameplay_floor_and_independent_aligned_map_checkpoints'),.95,'verified');return result
        if index==max_actions:break
        s.transition('jogo');frame,f=s.capture('v3-room-visual-plan')
        if f['scene']!='jogo' or not f.get('player') or f['health'] is not None and f['health']<.25:raise RuntimeError('Room navigation preflight unavailable')
        if s.preflight_enemy(f):raise RuntimeError('Combat interrupts room navigation')
        if goal_pixel is None:goal_pixel=[f['player'][i]+(target[i]-position[i])*ratio for i in range(2)]
        direction,ms=BombRockController.local_approach(frame,f,goal_pixel)
        row=s.pulse(Action('move',{'direction':direction,'ms':ms},'Follow the currently visible floor toward the room checkpoint'));controls.append(row['metrics'])
        motion=row['metrics']['motion'];goal_pixel=[goal_pixel[0]+motion['background_dx'],goal_pixel[1]+motion['background_dy']]
        if not s.last_features.get('player'):raise RuntimeError('Actor tracking lost after room movement')
        if (index+1)%3==0 or motion['confidence']<.25 or math.dist(s.last_features['player'],goal_pixel)<40:
            _,_,position,_=s.map_state('v3-room-progress-map');error=math.dist(position,target)
            if error>tolerance and error>=last_error-2:raise RuntimeError('Room checkpoint did not improve across the bounded visual sequence')
            last_error=error;goal_pixel=None
    raise RuntimeError('Local room navigation action budget exhausted')
