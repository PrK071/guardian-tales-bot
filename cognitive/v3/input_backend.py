"""Pinned scrcpy SDK touch channel. No root, game hooks or game-file changes."""
from pathlib import Path
import hashlib,json,secrets,socket,struct,subprocess,threading,time

class ScrcpyTouch:
    VERSION='3.3.2'
    def __init__(self,root,adb,folder,width=1600,height=900,video=False):
        self.root=Path(root);self.adb=adb;self.folder=Path(folder);self.width=width;self.height=height
        self.lock=threading.RLock();self.held={};self.events=[];self.sock=None;self.process=None;self.port=None;self.log=None
        self.scid=secrets.randbits(31);self.remote=f'/data/local/tmp/guardian-v3-{self.scid:08x}.jar';self.pushed=False
        self.video_enabled=video;self.video=None
    def connect(self):
        folder=self.root/'tools/scrcpy';manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'));jar=folder/f'scrcpy-server-v{self.VERSION}'
        if manifest['version']!=self.VERSION or hashlib.sha256(jar.read_bytes()).hexdigest()!=manifest['sha256']:raise RuntimeError('Pinned scrcpy server hash invalid')
        try:self.adb.call('push',str(jar),self.remote)
        except RuntimeError as exc:
            if 'not found' not in str(exc) and 'offline' not in str(exc):raise
            self.adb.connect();self.adb.call('push',str(jar),self.remote)
        self.pushed=True
        self.port=int(self.adb.call('forward','tcp:0',f'localabstract:scrcpy_{self.scid:08x}').decode().strip())
        self.folder.mkdir(parents=True,exist_ok=True);self.log=(self.folder/'scrcpy-server.log').open('wb')
        options=[f'scid={self.scid:08x}',f'video={str(self.video_enabled).lower()}','audio=false','control=true','tunnel_forward=true','send_device_meta=false','send_dummy_byte=true','clipboard_autosync=false','power_on=false','cleanup=false','log_level=debug']
        if self.video_enabled:options+=['video_codec=h264','max_size=1600','max_fps=20','video_bit_rate=16000000','downsize_on_error=false']
        args=[str(self.adb.exe),'-s',self.adb.serial,'shell',f'CLASSPATH={self.remote}','app_process','/','com.genymobile.scrcpy.Server',self.VERSION,*options]
        self.process=subprocess.Popen(args,stdout=self.log,stderr=subprocess.STDOUT,creationflags=0x08000000)
        deadline=time.monotonic()+12;last=None
        while time.monotonic()<deadline:
            if self.process.poll() is not None:raise RuntimeError('scrcpy server exited; inspect scrcpy-server.log')
            sock=None
            try:
                sock=socket.create_connection(('127.0.0.1',self.port),timeout=.5);sock.settimeout(.6)
                if sock.recv(1)!=b'\0':raise ConnectionError('scrcpy handshake not received')
                if self.video_enabled:
                    from .video import ScrcpyVideo
                    video_sock=sock
                    sock=socket.create_connection(('127.0.0.1',self.port),timeout=.5)
                    self.video=ScrcpyVideo(video_sock,self.width,self.height).start()
                sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);sock.settimeout(.4);self.sock=sock
                if self.video:self.video.frame_after(timeout=5)
                return self
            except (OSError,ConnectionError) as exc:
                last=exc
                if sock:sock.close()
                time.sleep(.05)
        raise RuntimeError('scrcpy control connection unavailable: '+str(last))
    def touch(self,pointer,action,x,y):
        if not isinstance(pointer,int) or not 0<=pointer<10 or action not in (0,1,2):raise ValueError('Invalid finger/action')
        x,y=round(x),round(y)
        if not 0<=x<self.width or not 0<=y<self.height:raise ValueError('Touch outside calibrated display')
        with self.lock:
            if self.sock is None:raise RuntimeError('Persistent touch channel disconnected')
            if action==0 and pointer in self.held:raise ValueError('Finger already down')
            if action in (1,2) and pointer not in self.held:raise ValueError('Finger is not down')
            # With video enabled Android maps coordinates from encoded video
            # dimensions. A size mismatch is silently ignored by Controller.
            video=getattr(self,'video',None)
            wire_width,wire_height=video.latest[1]['encoded_size'] if video else (self.width,self.height)
            wire_x=round(x*wire_width/self.width);wire_y=round(y*wire_height/self.height)
            payload=struct.pack('>BBQiiHHHII',2,action,pointer,wire_x,wire_y,wire_width,wire_height,0 if action==1 else 65535,0,0)
            start=time.perf_counter();self.sock.sendall(payload);end=time.perf_counter()
            if action==1:self.held.pop(pointer,None)
            else:self.held[pointer]=(x,y)
            self.events.append({'at':time.time(),'monotonic':end,'pointer':pointer,'action':action,'point':[x,y],'wire_point':[wire_x,wire_y],'wire_size':[wire_width,wire_height],'send_ms':(end-start)*1000,'delivery_confirmed':False})
    def down(self,pointer,x,y):self.touch(pointer,0,x,y)
    def move(self,pointer,x,y):self.touch(pointer,2,x,y)
    def up(self,pointer):
        with self.lock:
            if pointer in self.held:self.touch(pointer,1,*self.held[pointer])
    def release_all(self):
        errors=[]
        with self.lock:
            for pointer in list(self.held)[::-1]:
                try:self.up(pointer)
                except Exception as exc:errors.append(str(exc))
        if errors:raise RuntimeError('Release not confirmed: '+'; '.join(errors))
    def close(self):
        errors=[];cleanup_errors=[]
        try:self.release_all()
        except Exception as exc:errors.append(str(exc))
        if self.sock:
            self.sock.close();self.sock=None
        video=self.video.close() if self.video else None
        if self.process:
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=3)
        if self.log:self.log.close()
        if self.port:
            try:self.adb.call('forward','--remove',f'tcp:{self.port}')
            except Exception as exc:cleanup_errors.append(str(exc))
        if self.pushed:
            try:self.adb.call('shell','rm','-f',self.remote)
            except Exception as exc:cleanup_errors.append(str(exc))
        return {'release_errors':errors,'cleanup_errors':cleanup_errors,'fingers_remaining_locally':list(self.held),'events':self.events,'video':video}
