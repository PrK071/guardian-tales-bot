"""Reconnect only the exact observed game connection-loss prompt."""
from pathlib import Path
import json,sys,time
import cv2
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from bot import Bot,RapidOCR,norm
from cognitive.contracts import uid
bot=Bot();bot.ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2);folder=ROOT/'data/v3'/uid('v3_reconnection');folder.mkdir();events=[]
frame,snap=bot.observe();cv2.imwrite(str(folder/'before.jpg'),frame);text=norm(' '.join(w['text'] for w in snap['words']));(folder/'before.json').write_text(json.dumps(snap,ensure_ascii=False,indent=2),encoding='utf-8')
reference=cv2.imread(str(ROOT/'data/v3/v3_input_probe_6e69dadd34664215/0001-initial.jpg'))
same_prompt=reference is not None and float(cv2.matchTemplate(frame[390:465,650:960],reference[390:465,650:960],cv2.TM_CCOEFF_NORMED)[0,0])>.98
if not same_prompt and ('conexaoperdida' not in text.replace(' ','') or 'reconectar' not in text):raise RuntimeError('Exact connection-loss prompt not currently observed')
buttons=[w for w in snap['words'] if norm(w['text']).strip()=='confirma' and w['x']>.5 and w['y']>.7]
if len(buttons)==1:button=buttons[0]
elif same_prompt and float(cv2.matchTemplate(frame[694:760,807:1072],reference[694:760,807:1072],cv2.TM_CCOEFF_NORMED)[0,0])>.98:button={'x':939.5/1600,'y':727/900}
else:raise RuntimeError('Observed reconnect button absent/ambiguous')
if not bot.adb.foreground():raise RuntimeError('Game not foreground')
bot.adb.tap(button['x'],button['y'],1600,900);events.append({'action':'confirm_observed_game_reconnection','point':[button['x'],button['y']],'at':time.time()})
deadline=time.monotonic()+40;result=None
for index in range(15):
    frame,snap=bot.observe();cv2.imwrite(str(folder/f'{index:02d}-{snap["scene"]}.jpg'),frame);text=norm(' '.join(w['text'] for w in snap['words']))
    if 'conexao perdida' in text:result='connection_loss_persists';break
    if snap['scene'] in ('pausa','jogo','mapa','entrada') or 'aventura' in text:result=snap['scene'];break
    if time.monotonic()>deadline:result='reconnection_timeout';break
    time.sleep(.2)
(folder/'report.json').write_text(json.dumps({'events':events,'result':result,'snapshot':snap},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'folder':str(folder),'result':result},ensure_ascii=False))
