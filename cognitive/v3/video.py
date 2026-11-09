"""Latest-frame H.264 reader for the pinned scrcpy protocol (no input)."""
import struct,threading,time
from fractions import Fraction

class ScrcpyVideo:
    def __init__(self,sock,width,height):
        self.sock=sock;self.width=width;self.height=height;self.done=threading.Event();self.condition=threading.Condition()
        self.latest=None;self.sequence=0;self.error=None;self.samples=[]
        self.thread=threading.Thread(target=self._run,daemon=True,name='v3-video')
    def exact(self,size):
        data=bytearray()
        while len(data)<size:
            if self.done.is_set():raise InterruptedError('Video reader closed')
            try:part=self.sock.recv(size-len(data))
            except TimeoutError:continue
            if not part:raise ConnectionError('Video stream ended')
            data.extend(part)
        return bytes(data)
    def start(self):self.thread.start();return self
    def _run(self):
        try:
            import av
            codec,width,height=struct.unpack('>III',self.exact(12))
            if codec!=0x68323634 or abs(width-self.width)>7 or abs(height-self.height)>7:raise RuntimeError(f'Unexpected scrcpy codec/display geometry: {codec:08x} {width}x{height}')
            decoder=av.CodecContext.create('h264','r');decoder.thread_count=1;configuration=b''
            while not self.done.is_set():
                flags,size=struct.unpack('>QI',self.exact(12))
                if not 0<size<=16*1024*1024:raise RuntimeError('Invalid scrcpy frame size')
                payload=self.exact(size);received=time.perf_counter()
                if flags>>63:
                    configuration=payload;continue
                packet=av.Packet(configuration+payload);configuration=b''
                packet.pts=flags&((1<<62)-1);packet.time_base=Fraction(1,1000000)
                for decoded in decoder.decode(packet):
                    frame=decoded.to_ndarray(format='bgr24');finished=time.perf_counter()
                    if frame.shape[:2]!=(height,width):raise RuntimeError('Stream resized; calibration invalid')
                    if (width,height)!=(self.width,self.height):
                        # MediaCodec aligns the virtual display to 8 pixels.
                        # Normalize the full virtual display, never crop a HUD.
                        import cv2
                        frame=cv2.resize(frame,(self.width,self.height),interpolation=cv2.INTER_LINEAR)
                    with self.condition:
                        self.sequence+=1
                        sample={'sequence':self.sequence,'received_monotonic':received,'decoded_monotonic':finished,'decode_ms':(finished-received)*1000,'pts_us':packet.pts,'packet_bytes':size,'encoded_size':[width,height],'normalized_size':[self.width,self.height]}
                        self.latest=(frame,sample);self.samples.append(sample);self.condition.notify_all()
        except Exception as exc:
            if not self.done.is_set():
                with self.condition:self.error=type(exc).__name__+': '+str(exc);self.condition.notify_all()
    def frame_after(self,sequence=0,timeout=1.6):
        deadline=time.monotonic()+timeout
        with self.condition:
            while self.sequence<=sequence:
                if self.error:raise RuntimeError(self.error)
                if self.done.is_set():raise InterruptedError('Video reader closed')
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('No fresh video frame')
                self.condition.wait(remaining)
            frame,sample=self.latest
            if time.perf_counter()-sample['received_monotonic']>timeout:raise TimeoutError('Latest video frame stale')
            return frame.copy(),dict(sample)
    def close(self):
        self.done.set()
        try:self.sock.shutdown(2)
        except OSError:pass
        self.sock.close();self.thread.join(timeout=2)
        with self.condition:self.condition.notify_all()
        return {'frames':len(self.samples),'samples':self.samples,'error':self.error,'thread_stopped':not self.thread.is_alive()}
