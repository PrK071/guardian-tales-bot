"""Compile typed stage objectives before play; external prose is never code."""
import hashlib,json,math,re,time
from ..contracts import Provenance
from ..perception import normalize

KINDS={'navigate','encounter','explore','puzzle','exit'}

def observed_mode(observation):
    text=normalize(observation.text)
    if re.search(r'\bnormal\b',text):return 'normal'
    if re.search(r'\b(pesadelo|nightmare)\b',text):return 'nightmare'
    return None

class WalkthroughPlanner:
    def __init__(self,root,memory,research=None):self.root=root;self.memory=memory;self.research=research
    @staticmethod
    def adequate(scope,text):
        groups=(('lantern','lanterna'),('torch','braseiro','tocha'),('branch','junction','rock','ramific'),('monster','combat','monstro'),('exit','saida'))
        return scope=='world:1:passage:1' and all(any(word in text for word in group) for group in groups)
    def ensure(self,scope,mode,anchor_id,game_version='unknown',goal_id=None):
        if not mode:raise RuntimeError('Stage mode must be observed before selecting a walkthrough')
        key=f'v3:stage-plan:{scope}:{mode}:{anchor_id}:{game_version}'
        cached=self.memory.retrieve(scope,kind='v3_stage_plan',include_global=False,limit=8)
        for entry in cached:
            if entry['content'].get('cache_key')==key and entry['validation'] in ('reported','verified'):
                self.validate(entry['content']);return {**entry['content'],'memory_id':entry['id'],'cache_hit':True}
        memories=self.memory.retrieve(scope,kind='research',include_global=False,limit=12)
        text=normalize(json.dumps([m['content'] for m in memories],ensure_ascii=False))
        adequate=self.adequate(scope,text)
        attempt_key=f'v3:walkthrough-attempt:{scope}:{mode}:{game_version}'
        if not adequate and self.research and not self.memory.cached(attempt_key):
            self.research.reset_budget();self.research.investigate(scope,'complete route objectives prerequisites puzzles lanterns final exit',goal_id);self.memory.cache(attempt_key,{'attempted_at':time.time()},86400)
            memories=self.memory.retrieve(scope,kind='research',include_global=False,limit=12);text=normalize(json.dumps([m['content'] for m in memories],ensure_ascii=False))
            adequate=self.adequate(scope,text)
        if scope!='world:1:passage:1' or mode!='normal':raise RuntimeError('Walkthrough sources stored; this stage/mode still needs a verified local compiler')
        if not adequate:raise RuntimeError('A complete relevant walkthrough was not found; do not begin a blind route')
        source=self.root/'data/v2/v2_lantern_calibration_cface23508d84a6d/navigation.jsonl'
        rows=[json.loads(line) for line in source.read_text(encoding='utf-8').splitlines()];indices=[0,1,6,7]
        if not all(rows[i].get('verified') and rows[i].get('aligned_map_motion',{}).get('verified') for i in indices):raise RuntimeError('Stored initial route is not validated')
        expected='bde52d502e873032794e805d93eb1ece6bcc04c7003588536d2bc90a175bef99'
        if anchor_id!=expected:raise RuntimeError('Current map reference differs from the recorded route; research must be reconciled')
        points=[rows[i]['aligned_map_motion']['after'] for i in indices]
        steps=[]
        for name,title,point in zip(('initial_stem','npc_bypass','north_corridor'),('Reach the first chamber','Pass beside the observed NPC','Follow the northern corridor'),points[:3]):
            steps.append({'id':name,'kind':'navigate','title':title,'target_reference':point,'tolerance':7,'allow_npc_bypass':True,'run':False,'checkpoint':{'aligned_map_endpoint':point},'validation':'verified_local_route_hint','source':str(source.relative_to(self.root))})
        steps.extend([
            {'id':'first_encounter','kind':'encounter','title':'Defeat the first observed enemy group','trigger_reference':points[3],'checkpoint':{'observed_enemy_then_distinct_absences':3},'validation':'reported_order_with_observed_trigger_route'},
            {'id':'west_and_junction','kind':'explore','title':'Traverse the western passage and find the branch','landmark':{'rock_and_bomb_candidates':True},'hazards':['moving_spike_columns'],'checkpoint':{'new_landmark_observed':True},'validation':'reported'},
            {'id':'reach_lantern_room','kind':'explore','title':'Use the combat branch to reach the portable brazier','landmark':{'portable_brazier':True},'alternative':'rocks may be opened with bomb or fire only after verified pickup','checkpoint':{'portable_brazier_currently_visible':True},'validation':'reported'},
            {'id':'lantern_puzzle','kind':'puzzle','title':'Carry and ignite the brazier, light the fixed lanterns, cross the barrier','resolver':'observed_lanterns','prerequisites':['current pickup affordance','carried object and fire confirmed','rocks may require the Mole Glove or verified burning'],'checkpoint':{'previously_blocked_edge_crossed':True},'validation':'reported'},
            {'id':'final_encounter','kind':'encounter','title':'Defeat the enemy beyond the lantern barrier','checkpoint':{'observed_enemy_then_distinct_absences':3},'validation':'reported'},
            {'id':'exit','kind':'exit','title':'Reach the observed exit and verify real stage completion','checkpoint':{'independent_completion_observations':2},'validation':'reported'}])
        urls=[]
        for memory in memories:
            for item in memory['content'].get('sources',[]):
                if isinstance(item,dict) and item.get('url') and item['url'] not in urls:urls.append(item['url'])
        plan={'schema':3,'scope':scope,'mode':mode,'anchor_id':anchor_id,'game_version':game_version,'cache_key':key,'created_at':time.time(),'source_memory_ids':[m['id'] for m in memories],'source_urls':urls,'steps':steps,'high_level_coverage':'entry through final exit','guide_validation':'reported; each execution checkpoint requires current evidence','model_calls_to_compile':0}
        plan['id']=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()[:20];self.validate(plan)
        mid=self.memory.remember('semantic','v3_stage_plan',scope,plan,Provenance('v3:walkthrough_compile',method='typed_scope_specific_objectives_from_reported_sources_and_verified_local_route'),.7,'reported',dedupe=key)
        return {**plan,'memory_id':mid,'cache_hit':False}
    @staticmethod
    def validate(plan):
        if plan.get('schema')!=3 or not plan.get('scope') or not plan.get('mode') or not 1<=len(plan.get('steps',[]))<=100:raise ValueError('Invalid stage plan')
        for step in plan['steps']:
            if step.get('kind') not in KINDS or not step.get('id') or not step.get('checkpoint'):raise ValueError('Unsupported high-level stage step')
            for field in ('target_reference','trigger_reference'):
                if field in step and (len(step[field])!=2 or any(not isinstance(n,(int,float)) or not math.isfinite(n) for n in step[field])):raise ValueError('Invalid checkpoint coordinates')
    def activate(self,plan,run_id,new_entry=False,entry_token=None):
        saved=self.memory.retrieve(plan['scope'],kind='v3_active_plan',include_global=False,limit=1)
        same_entry=not entry_token or saved and saved[0]['content'].get('entry_token')==entry_token
        if saved and not new_entry and same_entry and saved[0]['content'].get('plan_id')==plan['id']:
            active={**saved[0]['content'],'run_id':run_id,'resumed':True}
        else:active={'plan_id':plan['id'],'scope':plan['scope'],'mode':plan['mode'],'cursor':0,'states':{},'run_id':run_id,'resumed':False}
        if entry_token:active['entry_token']=entry_token
        self.save_active(active);return active
    def save_active(self,active):
        self.memory.remember('working','v3_active_plan',active['scope'],active,Provenance('v3:active_plan',method='persistent_high_level_cursor_and_visual_checkpoints'),.95,'verified',dedupe='v3:active-plan:'+active['scope'])
    def checkpoint(self,active,step,frame,completed=True,result=None):
        active['states'][step['id']]={'state':'completed' if completed else 'replan_needed','frame':frame,'result':result,'at':time.time()}
        if completed:active['cursor']+=1
        self.save_active(active)
    def divergence(self,plan,active,step,reason,frame,details=None):
        record={'plan_id':plan['id'],'step_id':step['id'],'source_memory_ids':plan['source_memory_ids'],'reason':reason,'frame':frame,'details':details,'scope':'current observation differs from this plan assumption; source is not globally contradicted'}
        self.memory.remember('episodic','v3_guide_divergence',plan['scope'],record,Provenance(frame,method='current_checkpoint_vs_reported_walkthrough'),.95,'verified')
        self.checkpoint(active,step,frame,False,record);return record
