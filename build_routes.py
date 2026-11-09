"""Compila o trecho de calibração em uma rota com fotos de referência."""
import json, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent
events=[json.loads(line) for line in (ROOT/'logs/calibration.jsonl').read_text(encoding='utf-8').splitlines()]
events=events[2:10]
dest=ROOT/'routes/mundo1_passagem1_inicio'; dest.mkdir(exist_ok=True)
steps=[]
for i,event in enumerate(events):
    a=event['args']; anchor=f'mundo1_passagem1_inicio/{i:03d}.png'
    shutil.copyfile(event['before'],ROOT/'routes'/anchor)
    if a[0]=='swipe':
        dx=float(a[3])-float(a[1]);dy=float(a[4])-float(a[2])
        direction=('right' if dx>0 else 'left') if abs(dx)>abs(dy) else ('down' if dy>0 else 'up')
        duration=int(a[5]); chunks=[]
        while duration: chunks.append(min(1500,duration));duration-=chunks[-1]
        for j,ms in enumerate(chunks):
            step={'op':'move','direction':direction,'ms':ms,'settle':1.5}
            if j==0: step.update(anchor=anchor,min_similarity=.91)
            steps.append(step)
    elif a[0]=='tap': steps.append({'op':'interact','ms':100,'anchor':anchor,'min_similarity':.91,'settle':2})
steps.append({'op':'pause','message':'Fim do trecho calibrado de aproximação. Próximo encontro ainda sem rota de fase completa.'})
(ROOT/'routes/mundo1_passagem1_inicio.json').write_text(json.dumps({'id':'mundo1_passagem1_inicio','name':'Mundo 1 · início da Passagem 1',
 'status':'Trecho inicial de 10 passos reproduzido nesta conta. Para antes do próximo encontro; não conclui a fase.',
 'scope':'world:1:passage:1','end_anchor':'mundo1_passagem1_inicio/end.png',
 'start':'Personagem parado no nascimento da Passagem 1, antes de caminhar para o norte.', 'steps':steps},ensure_ascii=False,indent=2),encoding='utf-8')
shutil.copyfile(events[-1]['after'],dest/'end.png')
empty=ROOT/'routes/passagem1_trecho_norte.json'
if empty.exists() and not json.loads(empty.read_text(encoding='utf-8')).get('steps'): empty.unlink()
print('Rota do trecho inicial criada com '+str(len(steps))+' passos.')
