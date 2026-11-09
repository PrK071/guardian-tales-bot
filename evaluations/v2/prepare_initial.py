"""Reproduce Passage 1 preparation using observed labels and the recorded card.

Menu preparation only: no character movement, purchases or stage-clear claims.
Requires the main server stopped. Leaves a newly entered stage paused at spawn.
"""
from pathlib import Path
import json,sys,time,urllib.request
import cv2
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from bot import Bot,RapidOCR,norm,similarity
from cognitive.contracts import Provenance,uid
from cognitive.map_navigation import PauseMap
from cognitive.map_anchor import SpawnMapAnchor
from cognitive.memory import Memory
from cognitive.perception import Interpreter

def locate_passage_card(frame,reference):
    template=reference[419:481,842:894];search=frame[150:730,250:1350]
    gray=cv2.cvtColor(search,cv2.COLOR_BGR2GRAY);best=None
    for scale in (.94,.97,1.,1.03,1.06,1.09,1.12,1.15,1.18):
        candidate=cv2.resize(template,None,fx=scale,fy=scale);scores=cv2.matchTemplate(gray,cv2.cvtColor(candidate,cv2.COLOR_BGR2GRAY),cv2.TM_CCOEFF_NORMED)
        _,score,_,point=cv2.minMaxLoc(scores)
        if best is None or score>best[0]:best=(score,point,candidate.shape[1],candidate.shape[0])
    score,(x,y),w,h=best
    if score<.90:raise RuntimeError('Passage 1 card appearance not confidently located')
    return ((250+x+w/2)/1600,(150+y+h/2)/900),score

def main():
    try:urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=1)
    except Exception:pass
    else:raise RuntimeError('Stop the main server before stage preparation')
    bot=Bot();bot.ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2);bot.adb.connect()
    folder=ROOT/'data/v2'/uid('v2_preparation');folder.mkdir();events=[];entered=False;exited=False;paused_new=False;identity_reobservations=0;empty_reobservations=0
    deadline=time.monotonic()+75;interpreter=Interpreter()
    reference=cv2.imread(str(ROOT/'data/v2/recovery-world.png'))
    def tap(point,label,snapshot):
        if len(events)>=9:raise RuntimeError('Preparation action budget exhausted')
        if not bot.adb.foreground():raise RuntimeError('Game left foreground during preparation')
        events.append({'at':time.time(),'label':label,'point':point,'before_frame':snapshot})
        bot.adb.tap(*point,1600,900)
        (folder/'events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
    def text_point(snapshot,label):
        matches=[w for w in snapshot['words'] if norm(w['text']).strip()==norm(label) and w['y']>.70]
        if len(matches)!=1:raise RuntimeError('Preparation target absent/ambiguous: '+label)
        return matches[0]['x'],matches[0]['y']
    for index in range(24):
        if time.monotonic()>deadline:raise RuntimeError('Preparation time budget exhausted')
        frame,snap=bot.observe();path=folder/f'{index:03d}-{snap["scene"]}.jpg';cv2.imwrite(str(path),frame)
        path.with_suffix('.json').write_text(json.dumps(snap,ensure_ascii=False,indent=2),encoding='utf-8')
        text=norm(' '.join(w['text'] for w in snap['words']));scene=snap['scene']
        if scene=='desconhecida' and not snap['words'] and empty_reobservations<3:
            empty_reobservations+=1;time.sleep(.5);continue
        if any(s in text for s in ('reviver','ressuscitar','pagamento','recarregar')):raise RuntimeError('Protected screen during preparation')
        if 'deseja voltar ao menu principal' in text:
            tap(text_point(snap,'Confirma'),'Confirm observed return to menu',str(path));exited=True
        elif scene=='resultado' and 'etapacompletada' in text.replace(' ','') and 'fechar' in text:
            tap((.50,.77),'Dismiss observed completed-stage reward as instructed on screen',str(path))
        elif 'pontosdeeventoobtidos' in text.replace(' ','') and 'fechar' in text:
            tap((.50,.77),'Dismiss observed event-points receipt as instructed on screen',str(path))
        elif scene=='pausa' and not entered:
            if 'passagem 1' not in text:raise RuntimeError('Unexpected paused stage')
            tap(text_point(snap,'Lobby'),'Reset observed unfinished Passage 1',str(path))
        elif scene=='mapa' or 'mapamundo' in text.replace(' ','') or (scene=='desconhecida' and 'mundo1florestakanterbury' in text.replace(' ','') and 'realizacao' in text):
            if events and events[-1]['label'].startswith('Select visually matched') and time.time()-events[-1]['at']<10:
                time.sleep(.5);continue
            if reference is None:raise RuntimeError('Recorded Passage 1 card reference missing')
            point,score=locate_passage_card(frame,reference)
            tap(point,'Select visually matched Passage 1 card, score '+str(round(score,3)),str(path))
        elif scene=='entrada':
            ob=interpreter.interpret(frame,snap,frame_path=str(path))
            if ob.stage!='world:1:passage:1' or 'derrote monstros' not in text:
                identity_reobservations+=1
                if identity_reobservations<=2:continue
                raise RuntimeError('Stage identity/objective mismatch after three observations')
            memory=Memory(ROOT/'data/cognitive.sqlite')
            try:memory.remember('semantic','stage_objective',ob.scope,{'objective':'Derrote monstros.','observation':ob.to_dict()},Provenance(str(path),method='observed_entry_screen_ocr'),.98,'verified',dedupe='v2:passage1:observed-objective')
            finally:memory.close()
            tap(text_point(snap,'Entrar'),'Enter observed Passage 1',str(path));entered=True
        elif scene=='jogo' and entered and not paused_new:
            tap((.106,.13),'Pause newly entered stage before any character input',str(path));paused_new=True
        elif scene=='pausa' and entered:
            ob=interpreter.interpret(frame,snap,frame_path=str(path));state=PauseMap().parse(frame)
            memory=Memory(ROOT/'data/cognitive.sqlite')
            try:
                anchors=memory.retrieve('world:1:passage:1',kind='v2_spawn_anchor',include_global=False,limit=1)
                spawn=SpawnMapAnchor.load(anchors[0]['content'],ROOT).is_spawn(state) if anchors and anchors[0]['validation']=='verified' else 0<=state['bbox'][1]+state['bbox'][3]-state['player'][1]<35
            finally:memory.close()
            if ob.stage!='world:1:passage:1' or not spawn:raise RuntimeError('New stage spawn not verified')
            report={'kind':'menu_preparation_not_stage_execution','folder':str(folder),'stage':ob.stage,'initial_spawn_verified':True,'frame':str(path),'events':events,'character_movements':0}
            memory=Memory(ROOT/'data/cognitive.sqlite')
            try:memory.remember('working','v2_prepared_spawn',ob.scope,{'frame':str(path),'stage':ob.stage,'prepared_at':time.time(),'character_movements':0},Provenance(str(path),method='observed_entry_then_no_movement_pause'),.98,'verified',dedupe='v2:prepared-spawn:'+ob.scope)
            finally:memory.close()
            (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False));return
        elif any(norm(w['text']).strip()=='aventura' and w['y']>.80 for w in snap['words']):
            matches=[w for w in snap['words'] if norm(w['text']).strip()=='aventura' and w['y']>.80]
            if len(matches)!=1:raise RuntimeError('Adventure target ambiguous')
            tap((matches[0]['x'],matches[0]['y']),'Open observed Adventure menu',str(path))
        elif scene=='carregando':time.sleep(.25)
        else:raise RuntimeError('Unknown preparation state: '+scene)
    raise RuntimeError('Preparation observation budget exhausted')
if __name__=='__main__':main()
