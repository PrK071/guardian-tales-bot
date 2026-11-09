from pathlib import Path
from types import SimpleNamespace
import struct,threading,time,unittest
from cognitive.v3.input_backend import ScrcpyTouch
from cognitive.v3.continuous import ContinuousActions

class Socket:
    def __init__(self):self.packets=[]
    def sendall(self,payload):self.packets.append((time.perf_counter(),payload))

def backend():
    b=ScrcpyTouch.__new__(ScrcpyTouch);b.width=1600;b.height=900;b.lock=threading.RLock();b.held={};b.events=[];b.sock=Socket();return b
CONTROLS={'joystick':[.1475,.737],'joystick_radius':.13,'attack':[.748,.814],'interact':[.896,.815],'skill':[.791,.628]}

class ContinuousTests(unittest.TestCase):
    def test_video_coordinates_use_announced_encoder_size(self):
        b=backend();b.video=SimpleNamespace(latest=(None,{'encoded_size':[1600,904]}));b.down(0,236,663)
        fields=struct.unpack('>BBQiiHHHII',b.sock.packets[0][1])
        self.assertEqual(fields[3:7],(236,666,1600,904));b.release_all();self.assertEqual(b.held,{})
    def test_touch_wire_layout_matches_pinned_android_reader(self):
        b=backend();b.down(2,1434,733);payload=b.sock.packets[0][1]
        self.assertEqual(len(payload),32);self.assertEqual(struct.unpack('>BBQiiHHHII',payload),(2,0,2,1434,733,1600,900,65535,0,0));b.release_all();self.assertEqual(b.held,{})
    def test_attack_hold_sends_one_down_one_up_for_many_cycles(self):
        b=backend();c=ContinuousActions(b,CONTROLS)
        try:result=c.attack_hold(200)
        finally:c.close()
        self.assertEqual([e['action'] for e in b.events],[0,1]);self.assertGreaterEqual(result['actual_ms'],190)
    def test_move_and_attack_use_distinct_live_fingers(self):
        b=backend();c=ContinuousActions(b,CONTROLS)
        try:c.move_attack_hold('up',80)
        finally:c.close()
        down=[e['pointer'] for e in b.events if e['action']==0];self.assertEqual(down,[0,1]);self.assertEqual(b.held,{})
    def test_exception_in_observer_releases_every_finger(self):
        b=backend();c=ContinuousActions(b,CONTROLS)
        try:
            with self.assertRaisesRegex(RuntimeError,'perception failed'):c.move_attack_hold('left',1000,monitor=lambda:(_ for _ in ()).throw(RuntimeError('perception failed')))
        finally:c.close()
        self.assertEqual(b.held,{})
    def test_cancel_releases_during_slow_observation(self):
        b=backend();cancel=threading.Event();c=ContinuousActions(b,CONTROLS,cancel);started=threading.Event()
        def observer():started.set();time.sleep(.35)
        errors=[]
        def action():
            try:c.attack_hold(2000,monitor=observer)
            except InterruptedError:errors.append('stopped')
        thread=threading.Thread(target=action);thread.start();self.assertTrue(started.wait(1));at=time.perf_counter();cancel.set()
        while b.held and time.perf_counter()-at<.2:time.sleep(.005)
        self.assertEqual(b.held,{});self.assertLess(time.perf_counter()-at,.2);thread.join(1);c.close();self.assertEqual(errors,['stopped'])
    def test_run_requires_observed_boots(self):
        b=backend();c=ContinuousActions(b,CONTROLS,run_allowed=lambda:False)
        try:
            with self.assertRaisesRegex(RuntimeError,'boots'):c.move_hold('up',200,run=True)
        finally:c.close()
        self.assertEqual(b.events,[])
    def test_invalid_sequence_is_rejected_before_first_touch(self):
        b=backend();c=ContinuousActions(b,CONTROLS)
        try:
            with self.assertRaises(ValueError):c.execute_sequence([{'op':'attack_hold','duration_ms':100},{'op':'unknown'}])
        finally:c.close()
        self.assertEqual(b.events,[])
    def test_duration_release_does_not_wait_for_slow_capture(self):
        b=backend();c=ContinuousActions(b,CONTROLS)
        try:result=c.attack_hold(400,monitor=lambda:time.sleep(.30))
        finally:c.close()
        self.assertLess(result['actual_ms'],490);self.assertGreater(result['wall_ms'],600);self.assertEqual(b.held,{})
    def test_invalid_later_argument_does_not_partly_execute_sequence(self):
        b=backend();c=ContinuousActions(b,CONTROLS)
        try:
            with self.assertRaises(ValueError):c.execute_sequence([{'op':'attack_hold','duration_ms':100},{'op':'use_skill','unexpected':True}])
        finally:c.close()
        self.assertEqual(b.events,[])
    def test_adjacent_normal_attacks_merge_without_releasing_between_hits(self):
        b=backend();c=ContinuousActions(b,CONTROLS)
        try:rows=c.execute_sequence([{'op':'attack_hold','duration_ms':80},{'op':'attack_hold','duration_ms':80}])
        finally:c.close()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['planned_action_indices'],[0,1]);self.assertEqual([e['action'] for e in b.events],[0,1])

if __name__=='__main__':unittest.main()
