"""Continuous local actions. One touch down/up pair, not one command per hit."""
import math,threading,time

VECTORS={'up':(0,-1),'down':(0,1),'left':(-1,0),'right':(1,0),'up_left':(-.707,-.707),'up_right':(.707,-.707),'down_left':(-.707,.707),'down_right':(.707,.707)}

class ContinuousActions:
    def __init__(self,backend,controls,cancel=None,stop_paths=(),run_allowed=None,on_action=None):
        self.backend=backend;self.controls=controls;self.cancel=cancel or threading.Event();self.stop_paths=tuple(stop_paths)
        self.run_allowed=run_allowed;self.on_action=on_action;self.closed=threading.Event();self.aborted=threading.Event();self.stop_reason=None
        self.actions=[];self.stops=[];self.watch=threading.Thread(target=self._watch,daemon=True);self.watch.start()
    def _watch(self):
        while not self.closed.wait(.025):
            if self.cancel.is_set() or any(p.exists() for p in self.stop_paths):
                self.stop('manual_stop');return
    def check(self):
        if self.closed.is_set():raise RuntimeError('Continuous controller closed')
        if self.cancel.is_set() or any(p.exists() for p in self.stop_paths):self.stop('manual_stop')
        if self.aborted.is_set():raise InterruptedError(self.stop_reason or 'Continuous actions stopped')
    def stop(self,reason='manual_stop'):
        requested=time.perf_counter();self.stop_reason=reason;self.aborted.set();error=None
        try:self.backend.release_all()
        except Exception as exc:error=str(exc)
        self.stops.append({'at':time.time(),'reason':reason,'release_ms':(time.perf_counter()-requested)*1000,'error':error,'delivery_confirmed':False})
    @staticmethod
    def vector(direction):
        vector=VECTORS.get(direction) if isinstance(direction,str) else direction
        if not isinstance(vector,(list,tuple)) or len(vector)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in vector):raise ValueError('Invalid movement direction')
        norm=math.hypot(*vector)
        if norm<.001:raise ValueError('Zero movement direction')
        return vector[0]/norm,vector[1]/norm
    @staticmethod
    def duration(duration_ms):
        if isinstance(duration_ms,bool) or not isinstance(duration_ms,(int,float)) or not math.isfinite(duration_ms) or not 40<=duration_ms<=30000:raise ValueError('Continuous duration outside 40..30000ms safety envelope')
        return duration_ms/1000
    def point(self,name):
        x,y=self.controls[name];return x*self.backend.width,y*self.backend.height
    def _hold(self,kind,duration_ms,points,monitor=None,metadata=None):
        seconds=self.duration(duration_ms);self.check();start=time.perf_counter();owned=[];outcome='duration_elapsed';error=None
        row={'kind':kind,'requested_ms':duration_ms,'at_start':time.time(),'start_monotonic':start,**(metadata or {})};timer=None;timer_errors=[]
        try:
            for pointer,initial,final in points:
                with self.backend.lock:
                    self.check();self.backend.down(pointer,*initial);owned.append(pointer)
                    if final!=initial:self.backend.move(pointer,*final)
            deadline=start+seconds;next_observe=start+.35
            def release_at_deadline():
                for pointer in owned[::-1]:
                    try:self.backend.up(pointer)
                    except Exception as exc:timer_errors.append(str(exc))
            timer=threading.Timer(max(0,deadline-time.perf_counter()),release_at_deadline);timer.daemon=True;timer.start()
            while time.perf_counter()<deadline:
                self.check()
                if monitor and time.perf_counter()>=next_observe:
                    reason=monitor()
                    self.check()
                    if reason:outcome=reason;break
                    next_observe=time.perf_counter()+.05  # capture itself dominates cadence
                self.aborted.wait(min(.02,max(0,deadline-time.perf_counter())))
        except Exception as exc:
            error=type(exc).__name__+': '+str(exc);outcome='interrupted' if isinstance(exc,InterruptedError) else 'failed';raise
        finally:
            if timer:timer.cancel();timer.join(timeout=.5)
            release_errors=list(timer_errors)
            for pointer in owned[::-1]:
                try:self.backend.up(pointer)
                except Exception as exc:release_errors.append(str(exc))
            end=time.perf_counter();released=[e['monotonic'] for e in self.backend.events if e['action']==1 and e['pointer'] in owned and e['monotonic']>=start]
            row.update(end_monotonic=end,actual_ms=((max(released) if released else end)-start)*1000,wall_ms=(end-start)*1000,outcome=outcome,error=error,release_errors=release_errors,fingers_remaining=list(self.backend.held),observed_effect_verified=False)
            self.actions.append(row)
            if self.on_action:self.on_action(row)
            if release_errors and error is None:raise RuntimeError('Control release failed: '+'; '.join(release_errors))
        return row
    def move_hold(self,direction,duration_ms,run=False,monitor=None):
        vx,vy=self.vector(direction);center=self.point('joystick');radius=self.controls['joystick_radius']*self.backend.height
        endpoint=(center[0]+vx*radius,center[1]+vy*radius);points=[(0,center,endpoint)]
        if run:
            if not self.run_allowed or not self.run_allowed():raise RuntimeError('Running button is not the verified neutral boots affordance')
            point=self.point('interact');points.append((2,point,point))
        return self._hold('move_hold',duration_ms,points,monitor,{'direction':direction,'run':bool(run)})
    def attack_hold(self,duration_ms,monitor=None):
        point=self.point('attack');return self._hold('attack_hold',duration_ms,[(1,point,point)],monitor)
    def use_skill(self):
        point=self.point('skill');return self._hold('use_skill',100,[(3,point,point)])
    def move_attack_hold(self,direction,duration_ms,monitor=None):
        vx,vy=self.vector(direction);center=self.point('joystick');radius=self.controls['joystick_radius']*self.backend.height;point=self.point('attack')
        return self._hold('move_attack_hold',duration_ms,[(0,center,(center[0]+vx*radius,center[1]+vy*radius)),(1,point,point)],monitor,{'direction':direction})
    def execute_sequence(self,actions,monitor=None):
        if not isinstance(actions,list) or not 1<=len(actions)<=20:raise ValueError('Sequence requires 1..20 planned actions')
        # Validate the complete sequence before pressing anything.
        for item in actions:
            if not isinstance(item,dict) or item.get('op') not in ('move_hold','attack_hold','use_skill','move_attack_hold'):raise ValueError('Unsupported sequence operation')
            allowed={'move_hold':{'op','direction','duration_ms','run'},'move_attack_hold':{'op','direction','duration_ms'},'attack_hold':{'op','duration_ms'},'use_skill':{'op'}}[item['op']]
            if set(item)-allowed:raise ValueError('Unexpected sequence argument')
            if 'run' in item and not isinstance(item['run'],bool):raise ValueError('Running flag must be boolean')
            if item['op']!='use_skill':self.duration(item.get('duration_ms'))
            if item['op'] in ('move_hold','move_attack_hold'):self.vector(item.get('direction'))
        groups=[]
        for index,item in enumerate(actions):
            key=(item['op'],self.vector(item['direction']) if 'direction' in item else None,item.get('run',False))
            if groups and item['op']!='use_skill' and groups[-1]['key']==key and groups[-1]['item']['duration_ms']+item['duration_ms']<=30000:
                groups[-1]['item']['duration_ms']+=item['duration_ms'];groups[-1]['indices'].append(index)
            else:groups.append({'key':key,'item':dict(item),'indices':[index]})
        results=[]
        try:
            for group in groups:
                item=group['item']
                self.check();args={k:v for k,v in item.items() if k!='op'}
                if item['op']!='use_skill':args['monitor']=monitor
                result=getattr(self,item['op'])(**args);result['planned_action_indices']=group['indices'];results.append(result)
                if result['outcome']!='duration_elapsed':break
        finally:self.backend.release_all()
        return results
    def close(self):
        self.closed.set();self.backend.release_all();self.watch.join(timeout=.2)
