"""Reuse a fresh completed action observation, never an independent checkpoint."""
import time
from ..spatial import SpatialVision

def motion_after_pulse(session,controller,row,before,before_features,label):
    controller.check();row=row or {};features=getattr(session,'last_features',None);frame=getattr(session,'last_frame',None)
    cached=bool(features and frame is not None and features.get('frame')==row.get('after',{}).get('frame') and 0<=time.time()-features.get('at',0)<=.35 and features.get('scene')=='jogo' and features.get('player') and not features.get('combat_present',features.get('enemy_count')) and (features.get('health') is None or features['health']>=.30))
    if not cached:frame,features=controller.observe(label)
    same_pair=bool(cached and row.get('before',{}).get('frame')==before_features['frame'])
    if 'metrics' in row:row['metrics']['post_action_observation_reused']=cached;row['metrics']['post_action_motion_pair_reused']=same_pair
    motion=row['metrics']['motion'] if same_pair else SpatialVision.motion(before,frame,before_features['player'],features['player'])
    return frame,features,motion
