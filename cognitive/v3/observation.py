"""Capture while a finger remains down; control reads snapshots without waiting."""
import threading,time

class ThreatGate:
    """A nearby threat stops immediately; distant tiny bars need two frames."""
    def __init__(self):self.last_sequence=None;self.consecutive=0
    def update(self,snapshot):
        features=snapshot['features'];present=features.get('combat_present',bool(features['enemy_count']))
        if not present:self.consecutive=0;self.last_sequence=snapshot['sequence'];return False
        if features.get('focused_enemy_hp'):return True
        player=features.get('player')
        if not player:return True
        import math
        for entity in features.get('entities',[]):
            if entity['kind']!='enemy':continue
            x,y,w,h=entity['bbox']
            if math.dist(player,[x+w/2,y+h-10])<240:return True
        # Isolated tiny red fragments at the far/top cave boundary caused
        # false encounters in real preparations. Recheck from the bounded
        # route checkpoint; nearby bars and focused HP remain immediate.
        if features.get('enemy_red_area',100)<100:return False
        if snapshot['sequence']!=self.last_sequence:self.consecutive+=1;self.last_sequence=snapshot['sequence']
        return self.consecutive>=2

class LiveObserver:
    def __init__(self,session,stale_seconds=1.6):
        self.session=session;self.stale_seconds=stale_seconds;self.lock=threading.Lock();self.done=threading.Event();self.error=None;self.samples=[];self.sequence=0
        self.features=session.last_features;self.frame=session.last_frame;self.started=time.perf_counter()
        self.capture_start=self.started;self.capture_finish=self.started
        self.thread=threading.Thread(target=self._loop,daemon=True)
    def start(self):self.thread.start();return self
    def _loop(self):
        while not self.done.is_set():
            start=time.perf_counter()
            try:frame,features=getattr(self.session,'capture_live',self.session.capture)('v3-live-observation')
            except Exception as exc:
                with self.lock:self.error=type(exc).__name__+': '+str(exc)
                return
            end=time.perf_counter()
            with self.lock:
                self.frame=frame;self.features=features;self.sequence+=1;self.capture_start=start;self.capture_finish=end
                self.samples.append({'sequence':self.sequence,'capture_wall_ms':(end-start)*1000,'acquisition_ms':features['capture_ms'],'capture_source':features.get('capture_source','android_raw'),'raw_capture_ms':features['capture_ms'] if not features.get('video_sample') else None,'frame':features['frame'],'scene':features['scene']})
            video=features.get('video_sample')
            if video:
                with self.lock:self.capture_start=video['received_monotonic']
            self.done.wait(max(0,(.08 if video else .35)-(end-start)))
    def snapshot(self):
        with self.lock:return {'sequence':self.sequence,'features':self.features,'frame':self.frame,'error':self.error,'age_seconds':time.perf_counter()-self.capture_start,'capture_start':self.capture_start,'capture_finish':self.capture_finish}
    def reason(self,policy):
        snap=self.snapshot()
        if snap['error']:return 'perception_error: '+snap['error']
        if snap['age_seconds']>self.stale_seconds:return 'perception_stale'
        return policy(snap)
    def close(self):
        self.done.set();self.thread.join(timeout=16)
        if self.thread.is_alive():raise RuntimeError('Observation thread did not stop after ADB timeout bound')
        return {'captures':self.samples,'error':self.error,'seconds':time.perf_counter()-self.started}
