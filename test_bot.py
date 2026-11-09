import json, tempfile, unittest
from pathlib import Path
import cv2
import numpy as np
import bot

class DummyADB:
    def __init__(self): self.calls=[]
    def foreground(self): return True
    def tap(self,*args): self.calls.append(('tap',args))
    def hold(self,*args): self.calls.append(('hold',args))
    def move(self,*args): self.calls.append(('move',args))

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.b=bot.Bot(); self.b.adb=DummyADB()
        self.frame=np.full((900,1600,3),120,np.uint8)
        self.snap={'scene':'jogo','blocked':None,'words':[],'width':1600,'height':900}
        self.b.observe=lambda: (self.frame,self.snap)
    def test_no_input_when_stopped(self):
        self.b.cancel.set()
        with self.assertRaises(InterruptedError): self.b.execute({'op':'attack'})
        self.assertEqual(self.b.adb.calls,[])
    def test_unique_text_click_uses_detected_position(self):
        self.snap['words']=[{'text':'Continuar','x':.8,'y':.9}]
        self.b.execute({'op':'text','text':'Continuar','settle':0})
        self.assertEqual(self.b.adb.calls,[('tap',(.8,.9,1600,900))])
    def test_attack_hold_is_bounded(self):
        self.b.execute({'op':'attack','ms':99999,'settle':0})
        self.assertEqual(self.b.adb.calls[0][1][2],1500)
    def test_shop_blocks_input(self):
        self.snap.update(scene='bloqueada',blocked='loja')
        with self.assertRaises(RuntimeError): self.b.execute({'op':'tap','x':.5,'y':.5})
        self.assertEqual(self.b.adb.calls,[])
    def test_unknown_scene_blocks_input(self):
        self.snap['scene']='desconhecida'
        with self.assertRaises(RuntimeError): self.b.execute({'op':'move','direction':'up'})
        self.assertEqual(self.b.adb.calls,[])
    def test_menu_blocks_combat(self):
        self.snap['scene']='mapa'
        with self.assertRaises(RuntimeError): self.b.execute({'op':'attack'})
        self.assertEqual(self.b.adb.calls,[])
    def test_ambiguous_text_is_not_clicked(self):
        self.snap['words']=[{'text':'Continuar','x':.5,'y':.8}]*2
        with self.assertRaises(RuntimeError): self.b.execute({'op':'text','text':'Continuar'})
        self.assertEqual(self.b.adb.calls,[])
    def test_checkpoint_mismatch_blocks_input(self):
        with tempfile.TemporaryDirectory(dir=bot.ROOT/'routes') as folder:
            p=Path(folder)/'anchor.png'; cv2.imwrite(str(p),np.zeros_like(self.frame))
            with self.assertRaisesRegex(RuntimeError,'Checkpoint divergiu'):
                self.b.execute({'op':'tap','x':.5,'y':.5,'anchor':str(p.relative_to(bot.ROOT/'routes')),'min_similarity':.9})
        self.assertEqual(self.b.adb.calls,[])
    def test_checkpoint_cannot_escape_routes(self):
        with self.assertRaises(ValueError): self.b.execute({'op':'tap','x':.5,'y':.5,'anchor':'../config.json'})
        self.assertEqual(self.b.adb.calls,[])
    def test_no_enemy_on_plain_frame(self):
        self.assertIsNone(bot.Bot.enemy_target(self.frame))
    def test_enemy_bar_and_red_clothes(self):
        frame=self.frame.copy(); frame[200:215,500:590]=0; frame[204:211,504:584]=(0,0,255)
        frame[430:440,760:820]=(0,0,255)
        target=bot.Bot.enemy_target(frame)
        self.assertIsNotNone(target); self.assertLess(target[1],250)
    def test_captured_game_hud(self):
        p=bot.ROOT/'captures/1794088457275347900-before.png'
        self.assertTrue(bot.Bot.game_hud(cv2.imread(str(p))))
        self.assertFalse(bot.Bot.game_hud(cv2.imread(str(bot.ROOT/'captures/initial.png'))))

if __name__=='__main__': unittest.main(verbosity=2)
