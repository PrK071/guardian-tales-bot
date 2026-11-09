"""Verified tool, carried fire, fixed-lantern views and the real stone gate."""
from ..contracts import Provenance
from ..lantern_control import LanternController
from .carry_combat import arrow_visible
from .fixed_lanterns import light_nearest
from .rock_glove import ensure_lantern_access
from .room_navigation import goto_room_checkpoint
from .lantern_gate import verify_and_cross

class LanternSegment:
    def __init__(self,session):self.s=session;self.controller=LanternController(session,seconds=480);self.events=[]
    def run(self):
        s=self.s;c=self.controller;s.transition('jogo');frame,f=s.capture('v3-lantern-segment-start')
        if arrow_visible(s,frame) and s.held_object_kind!='brazier':c.restore_held()
        active=s.memory.retrieve(s.scope,kind='v3_active_plan',include_global=False,limit=1)
        entry=active[0]['content'].get('entry_token') if active else None
        completed=s.memory.retrieve(s.scope,kind='v3_lantern_gate_crossing',include_global=False,limit=4)
        for checkpoint in completed:
            data=checkpoint['content']
            if checkpoint['validation']=='verified' and entry and data.get('entry_token')==entry:
                _,_,position,features=s.map_state('v3-puzzle-resume-crossing-check');edge=data['formerly_blocked_edge_reference']
                if position[1]>edge[1] and abs(position[0]-edge[0])<25:
                    return {**data,'verified':True,'after_reference':position,'crossing_map_frame':features['frame'],'resumed_from_verified_gate_crossing':checkpoint['id']}
        views=[]
        for viewpoint in ([426,713],[426,775]):
            goto_room_checkpoint(s,viewpoint);s.transition('jogo');frame,f=c.observe('v3-lantern-room-view')
            for _ in range(2):
                unlit=c.objects(f,'standing_lantern_unlit')
                if not unlit:break
                access=ensure_lantern_access(s,c,unlit[0]);self.events.append({'phase':'mole_glove_prerequisite','result':access})
                if access.get('tiles'):
                    # The glove lunges toward the tile and can push the floor
                    # torch beneath the on-screen joystick. Recover the room
                    # view before searching; do not select a stale object pose.
                    goto_room_checkpoint(s,viewpoint);s.transition('jogo');frame,f=c.observe('v3-lantern-return-after-glove')
                if not s.held_object_kind:
                    c.pickup();frame,f=c.observe('v3-lantern-fire-check')
                if s.lantern_vision.held_fire_pixels(s.last_frame,s.last_features['player'])<450:
                    self.events.append({'phase':'carried_fire','result':c.ignite()})
                    # Ignition verification moves away from the source. Return
                    # to this planned room view before choosing its unlit lamp.
                    goto_room_checkpoint(s,viewpoint);s.transition('jogo');c.observe('v3-lantern-return-after-ignition')
                result=light_nearest(s,c);self.events.append({'phase':'fixed_lantern','result':result})
                goto_room_checkpoint(s,viewpoint);s.transition('jogo');frame,f=c.observe('v3-lantern-room-view-recheck')
            lit=c.objects(f,'standing_lantern_lit');unlit=c.objects(f,'standing_lantern_unlit')
            if unlit or len(lit)<2:raise RuntimeError('Both fixed lanterns are not currently confirmed at the room viewpoint')
            views.append({'viewpoint_reference':viewpoint,'frame':f['frame'],'lit':lit})
        result=verify_and_cross(s);result.update(room_views=views,substeps=self.events)
        s.memory.remember('episodic','v3_lantern_segment',s.scope,{'run_id':s.run_id,**result},Provenance(result['crossing_map_frame'],method='both_room_views_lit_then_lowered_stone_and_map_crossing'),.95,'verified')
        return result
