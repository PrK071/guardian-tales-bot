from types import SimpleNamespace
import unittest,time
from unittest.mock import patch
from cognitive.v3.combat import CombatController

def features(sequence,enemy=True,health=1.,far=False,hazard=False):
    entities=[{'kind':'enemy','bbox':[1100 if far else 760,350,80,90]}] if enemy else []
    return {'scene':'jogo','player':[800,445],'health':health,'enemy_count':int(enemy),'hazard_count':int(hazard),'entities':entities,'enemy_red_area':1000-sequence*50 if enemy else 0,'frame':'synthetic:'+str(sequence),'at':0}

class Observer:
    stale_seconds=1.6
    def __init__(self,session):self.script=session.script;self.index=-1
    def start(self):return self
    def snapshot(self):
        self.index=min(self.index+1,len(self.script)-1);sequence,f=self.script[self.index]
        return {'sequence':sequence,'features':f,'frame':None,'error':None,'age_seconds':.1}
    def reason(self,policy):return policy(self.snapshot())
    def close(self):return {'captures':[],'error':None}

class Controls:
    def __init__(self):self.actions=[];self.backend=SimpleNamespace(release_all=lambda:None);self.reads=0;self.skills=0
    def execute(self,kind,monitor):
        reason=None
        if monitor:
            for _ in range(20):
                self.reads+=1;reason=monitor()
                if reason:break
        row={'kind':kind,'outcome':reason or 'duration_elapsed'};self.actions.append(row);return row
    def attack_hold(self,ms,monitor=None):return self.execute('attack_hold',monitor)
    def move_hold(self,direction,ms,monitor=None):return self.execute('move_hold',monitor)
    def use_skill(self):self.skills+=1;return self.execute('use_skill',None)

class CombatTests(unittest.TestCase):
    def run_case(self,script,skill_ready=None,prior=None):
        session=SimpleNamespace(script=script,last_features=script[0][1],memory=SimpleNamespace(remember=lambda *a,**k:None),scope='world:1:passage:1',run_id='simulation',check_cancel=lambda:None,transition=lambda scene:None,capture=lambda label:(None,script[0][1]))
        controls=Controls()
        with patch('cognitive.v3.combat.LiveObserver',Observer):result=CombatController(session,controls,skill_ready,prior).run(.2)
        return result,controls
    def test_enemy_killed_during_item_release_still_requires_three_distinct_absences(self):
        prior=features(0,True);prior['at']=time.time();script=[(n,features(n,False)) for n in range(3)]
        result,controls=self.run_case(script,prior=prior);self.assertTrue(result['visible_combat_ended']);self.assertEqual(len(result['clear_frames']),3);self.assertEqual(controls.actions,[])
    def test_old_or_unobserved_enemy_evidence_cannot_seed_a_clearance(self):
        for enemy,age in [(True,11),(False,0)]:
            prior=features(0,enemy);prior['at']=time.time()-age;result,_=self.run_case([(0,features(0,False))],prior=prior);self.assertFalse(result['visible_combat_ended'])
    def test_one_hold_covers_enemy_updates_until_three_distinct_absences(self):
        script=[(n,features(n,n<3)) for n in range(6)]
        result,controls=self.run_case(script)
        self.assertTrue(result['visible_combat_ended']);self.assertEqual([a['kind'] for a in controls.actions],['attack_hold']);self.assertEqual(len(result['clear_frames']),3);self.assertEqual(controls.actions[0]['outcome'],'enemy_not_visible')
    def test_duplicate_absent_frame_does_not_count_as_three_confirmations(self):
        script=[(0,features(0)),(1,features(1,False)),(1,features(1,False)),(1,features(1,False)),(2,features(2)),(3,features(3,False)),(4,features(4,False)),(5,features(5,False))]
        result,controls=self.run_case(script)
        self.assertTrue(result['visible_combat_ended']);self.assertEqual(result['clear_frames'],['synthetic:3','synthetic:4','synthetic:5']);self.assertEqual(len(controls.actions),2)
    def test_no_enemy_observed_is_not_a_combat_success(self):
        result,controls=self.run_case([(0,features(0,False))]);self.assertFalse(result['visible_combat_ended']);self.assertEqual(controls.actions,[])
    def test_hazard_during_approach_stops_instead_of_repeating_advance(self):
        result,controls=self.run_case([(0,features(0,far=True)),(1,features(1,far=True,hazard=True))])
        self.assertEqual(result['outcome'],'hazard_blocks_approach');self.assertEqual([a['kind'] for a in controls.actions],['move_hold'])
    def test_low_health_does_not_press_attack_when_retreat_unavailable(self):
        result,controls=self.run_case([(0,features(0,health=.15))]);self.assertFalse(result['visible_combat_ended']);self.assertEqual(controls.actions,[])
    def test_skill_requires_explicit_readiness_and_remains_separate_from_hits(self):
        script=[(n,features(n,n<3)) for n in range(6)]
        _,without=self.run_case(script);_,ready=self.run_case(script,lambda frame,f:True)
        self.assertEqual(without.skills,0);self.assertEqual(ready.skills,1);self.assertEqual(sum(a['kind']=='attack_hold' for a in ready.actions),1)

if __name__=='__main__':unittest.main()
