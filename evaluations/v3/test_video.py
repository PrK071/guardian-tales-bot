import socket,struct,time,unittest
import av,numpy as np
from cognitive.v3.video import ScrcpyVideo

class VideoTests(unittest.TestCase):
    def test_real_decoder_protocol_and_fresh_frame_contract(self):
        left,right=socket.socketpair();left.settimeout(.1);video=ScrcpyVideo(left,64,64).start()
        encoder=av.CodecContext.create('libx264','w');encoder.width=64;encoder.height=64;encoder.pix_fmt='yuv420p';encoder.options={'preset':'ultrafast','tune':'zerolatency'};encoder.open()
        frame=av.VideoFrame.from_ndarray(np.full((64,64,3),90,np.uint8),format='bgr24');packets=encoder.encode(frame)+encoder.encode(None)
        data=struct.pack('>III',0x68323634,64,64)
        for packet in packets:data+=struct.pack('>QI',0x4000000000000000,packet.size)+bytes(packet)
        try:
            # Fragment the headers and payload to exercise real socket framing.
            for index in range(0,len(data),17):right.sendall(data[index:index+17])
            decoded,sample=video.frame_after(timeout=2)
            self.assertEqual(decoded.shape,(64,64,3));self.assertLess(abs(float(decoded.mean())-90),4)
            with self.assertRaises(TimeoutError):video.frame_after(sample['sequence'],timeout=.08)
        finally:report=video.close();right.close()
        self.assertTrue(report['thread_stopped']);self.assertIsNone(report['error'])
    def test_bad_codec_is_reported_before_returning_an_image(self):
        left,right=socket.socketpair();left.settimeout(.1);video=ScrcpyVideo(left,64,64).start()
        try:
            right.sendall(struct.pack('>III',0,64,64))
            with self.assertRaisesRegex(RuntimeError,'codec/display'):video.frame_after(timeout=1)
        finally:video.close();right.close()
