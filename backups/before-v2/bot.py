"""Guardian Tales: visão local, rotas com checkpoints e painel de controle.

Não contém um solucionador universal da história. Rotas só são executadas
quando a tela coincide com um checkpoint registrado. O pacote cognitive
acrescenta planejamento, memória, pesquisa HTTP e modelo textual local.
"""
from __future__ import annotations
import argparse, collections, io, json, logging, math, os, queue, re, secrets
import subprocess, threading, time, unicodedata, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

ROOT = Path(__file__).resolve().parent
for folder in ('captures', 'logs', 'routes', 'knowledge'):
    (ROOT/folder).mkdir(exist_ok=True)
CONFIG = json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
logging.basicConfig(filename=ROOT/'logs/bot.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')
TOKEN = secrets.token_urlsafe(32)

def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s.lower()) if not unicodedata.combining(c))

class ADB:
    def __init__(self):
        self.exe = ROOT/CONFIG['adb']
        self.serial = CONFIG['serial']
    def call(self, *args, timeout=15):
        proc = subprocess.run([str(self.exe), '-s', self.serial, *map(str,args)],
                              capture_output=True, timeout=timeout, creationflags=0x08000000)
        if proc.returncode:
            raise RuntimeError(proc.stderr.decode('utf-8', errors='replace').strip() or 'Falha ADB')
        return proc.stdout
    def connect(self):
        subprocess.run([str(self.exe), 'connect', self.serial], capture_output=True,
                       timeout=10, creationflags=0x08000000)
        if self.call('get-state').strip() != b'device':
            raise RuntimeError('MSI desconectado; abra o emulador e ative o ADB.')
    def foreground(self):
        text = self.call('shell','dumpsys','activity','activities').decode(errors='replace')
        lines = [line for line in text.splitlines() if 'mResumedActivity' in line or 'topResumedActivity' in line]
        return any(CONFIG['package']+'/' in line for line in lines)
    def capture(self):
        raw = self.call('exec-out', 'screencap', '-p')
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if frame is None: raise RuntimeError('Captura Android inválida.')
        return frame
    def tap(self,x,y,w,h):
        self.call('shell','input','tap',round(x*w),round(y*h))
    def hold(self,x,y,ms,w,h):
        self.call('shell','input','swipe',round(x*w),round(y*h),round(x*w),round(y*h),ms)
    def move(self,direction,ms,w,h):
        directions = {'up':(0,-1),'down':(0,1),'left':(-1,0),'right':(1,0),
                      'up_left':(-.707,-.707),'up_right':(.707,-.707),
                      'down_left':(-.707,.707),'down_right':(.707,.707)}
        if direction not in directions: raise ValueError('Direção inválida')
        x,y=CONFIG['controls']['joystick']; dx,dy=directions[direction]
        radius=CONFIG['controls']['joystick_radius']*h
        self.call('shell','input','swipe',round(x*w),round(y*h),round(x*w+dx*radius),round(y*h+dy*radius),ms)

def similarity(frame, anchor, roi=None):
    if frame.shape[:2] != anchor.shape[:2]:
        anchor=cv2.resize(anchor,(frame.shape[1],frame.shape[0]))
    roi=roi or [0.22,0.17,0.72,0.66]
    h,w=frame.shape[:2]; x1,y1,x2,y2=[int(v*(w if i%2==0 else h)) for i,v in enumerate(roi)]
    if x2<=x1 or y2<=y1: raise ValueError('ROI inválida')
    a=cv2.resize(frame[y1:y2,x1:x2],(96,64)).astype(float)
    b=cv2.resize(anchor[y1:y2,x1:x2],(96,64)).astype(float)
    return float(1-np.mean(np.abs(a-b))/255)

class Bot:
    checkpoint_similarity=staticmethod(similarity)
    def __init__(self):
        self.adb=ADB(); self.ocr=None
        self.events=collections.deque(maxlen=60); self.jobs=queue.Queue(maxsize=5)
        self.cancel=threading.Event(); self.shutdown=threading.Event()
        self.lock=threading.RLock(); self.frame=None; self.jpeg=b''
        self.snapshot={}; self.mode='Inicializando'; self.note='Carregando visão local...'
        self.recording=None; self.recorded=[]; self.busy=False
        self.cognition=None
    def ensure_cognitive(self):
        if self.cognition is None:
            from cognitive.memory import Memory
            from cognitive.perception import LegacyEnvironment
            from cognitive.research import ResearchEngine
            from cognitive.runtime import CognitiveRuntime
            from cognitive.advisor import HttpAdvisor
            memory=Memory(ROOT/'data/cognitive.sqlite')
            settings=CONFIG.get('cognitive',{})
            research=ResearchEngine(memory,ROOT/'knowledge/worlds.json',max_requests=settings.get('max_research_requests',5))
            advisor_config=settings.get('advisor',{})
            if advisor_config.get('backend')=='llama_cpp':
                from cognitive.local_model import LocalLlamaAdvisor
                advisor=LocalLlamaAdvisor(ROOT,advisor_config)
            else:advisor=HttpAdvisor(advisor_config)
            self.cognition=CognitiveRuntime(LegacyEnvironment(self,ROOT),memory,research,advisor,ROOT/'logs/cognitive.jsonl')
            self.cognition.import_library(ROOT/'knowledge/worlds.json')
        return self.cognition
    def log(self,msg):
        with self.lock: self.events.appendleft(time.strftime('%H:%M:%S')+' '+msg)
        logging.info(msg)
    def observe(self, ocr=True):
        if not self.adb.foreground(): raise RuntimeError('Guardian Tales não está em primeiro plano no Android.')
        frame=self.adb.capture(); h,w=frame.shape[:2]
        words=[]
        if ocr:
            rows,_=self.ocr(frame)
            for box,text,score in rows or []:
                if score>=.65:
                    words.append({'text':text,'score':round(float(score),3),
                                  'x':float(np.mean([p[0] for p in box]))/w,
                                  'y':float(np.mean([p[1] for p in box]))/h})
        text=norm(' '.join(item['text'] for item in words))
        blocked=next((s for s in ('reviver','ressuscitar','comprar','pagamento','recarregar','summon','invocar','loja') if s in text),None)
        if blocked: scene='bloqueada'
        elif 'mapa mundo' in text: scene='mapa'
        elif 'entrar etapa' in text: scene='entrada'
        elif 'continuar' in text and 'lobby' in text: scene='pausa'
        elif 'carregando' in text or float(frame.mean())<8: scene='carregando'
        elif any(s in text for s in ('stage clear','etapa concluida','fase concluida','conclusao da etapa')): scene='resultado'
        elif self.game_hud(frame): scene='jogo'
        elif 'pular' in text or 'skip' in text: scene='dialogo'
        else: scene='desconhecida'
        snap={'scene':scene,'words':words,'blocked':blocked,'width':w,'height':h,'at':time.time()}
        _,jpg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,80])
        with self.lock:
            self.frame=frame; self.jpeg=jpg.tobytes(); self.snapshot=snap
        return frame,snap
    @staticmethod
    def game_hud(frame):
        h,w=frame.shape[:2]
        # Painel do minimapa à esquerda + barras de vida verdes no topo.
        hud=frame[int(.085*h):int(.12*h),int(.21*w):int(.33*w)]
        hsv=cv2.cvtColor(hud,cv2.COLOR_BGR2HSV)
        return np.count_nonzero(cv2.inRange(hsv,(35,80,45),(90,255,255)))>hud.shape[0]*hud.shape[1]*.025
    def check(self,snap,game_only=False):
        if self.cancel.is_set(): raise InterruptedError('Parado pelo usuário')
        if snap['blocked']: raise RuntimeError('Tela de '+snap['blocked']+': execução pausada.')
        if snap['scene'] in ('desconhecida','carregando'):
            raise RuntimeError('Tela sem identificação; precisa de um checkpoint ou de revisão.')
        if game_only and snap['scene']!='jogo': raise RuntimeError('Movimento/combate exige a tela da fase.')
    def execute(self, step, record=True):
        kind=step['op']
        if kind=='wait':
            if self.cancel.wait(min(15,max(.1,float(step.get('seconds',1))))): raise InterruptedError()
            return
        frame,snap=self.observe(); self.check(snap,kind in ('move','attack','skill','interact'))
        if step.get('anchor'):
            anchor_path=(ROOT/'routes'/step['anchor']).resolve()
            if not anchor_path.is_relative_to((ROOT/'routes').resolve()): raise ValueError('Checkpoint fora de routes')
            anchor=cv2.imread(str(anchor_path))
            if anchor is None: raise RuntimeError('Checkpoint ausente')
            score=similarity(frame,anchor,step.get('roi'))
            if score<float(step.get('min_similarity',.88)):
                raise RuntimeError(f'Checkpoint divergiu: {score:.2f}; não enviei o comando.')
        h,w=frame.shape[:2]; saved=dict(step)
        if self.recording and record:
            name=f'{self.recording}/step-{len(self.recorded):04d}.png'
            cv2.imwrite(str(ROOT/'routes'/name),frame); saved['anchor']=name
        if not self.adb.foreground(): raise RuntimeError('O aplicativo mudou durante a leitura da tela.')
        if self.cancel.is_set(): raise InterruptedError('Parado pelo usuário')
        if kind=='tap':
            x,y=float(step['x']),float(step['y'])
            if not 0<=x<=1 or not 0<=y<=1: raise ValueError('Coordenadas fora da tela')
            # Recursos e configurações ficam no topo. Toques ali só são feitos no jogo, via rotas explícitas.
            if snap['scene'] in ('mapa','entrada') and y<.11: raise RuntimeError('Topo do menu protegido.')
            self.adb.tap(x,y,w,h)
        elif kind=='text':
            targets=step.get('texts',[step.get('text','')]); matches=[]
            region=step.get('region',[0,0,1,1])
            for word in snap['words']:
                if norm(word['text']).strip() in [norm(t).strip() for t in targets] and region[0]<=word['x']<=region[2] and region[1]<=word['y']<=region[3]: matches.append(word)
            if len(matches)!=1: raise RuntimeError('Botão de texto ausente ou ambíguo: '+str(targets))
            self.adb.tap(matches[0]['x'],matches[0]['y'],w,h)
        elif kind=='move': self.adb.move(step['direction'],max(80,min(1500,int(step.get('ms',600)))),w,h)
        elif kind in ('attack','skill','interact'):
            point=CONFIG['controls'][kind]
            self.adb.hold(*point,max(80,min(1500,int(step.get('ms',600)))),w,h)
        else: raise ValueError('Ação não suportada: '+kind)
        if self.recording and record:
            self.recorded.append(saved); self.save_recording()
        self.log('Ação: '+kind+(' '+step['direction'] if kind=='move' else ''))
        if self.cancel.wait(float(step.get('settle',.6))): raise InterruptedError()
        self.observe()
    def save_recording(self):
        obj={'id':self.recording,'name':self.recording,'status':'gravada; revisar antes de repetir',
             'steps':self.recorded,'created':time.strftime('%Y-%m-%d %H:%M:%S')}
        path=ROOT/'routes'/(self.recording+'.json'); tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8'); tmp.replace(path)
    def route(self,name):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',name): raise ValueError('Nome de rota inválido')
        route=json.loads((ROOT/'routes'/(name+'.json')).read_text(encoding='utf-8'))
        deadline=time.monotonic()+600
        for i,step in enumerate(route['steps']):
            if time.monotonic()>deadline: raise RuntimeError('Limite de dez minutos da rota atingido')
            self.note=f'{route["name"]}: passo {i+1}/{len(route["steps"])}'
            if step['op']=='pause':
                message=step.get('message','Trecho ainda não programado.')
                self.log(message); return message
            if step['op']=='combat': self.combat(min(30,float(step.get('seconds',10)))); continue
            if step['op']=='wait_scene':
                end=time.monotonic()+min(30,float(step.get('timeout',20)))
                while True:
                    _,snap=self.observe()
                    if snap['scene']==step['scene']: break
                    if self.cancel.wait(.5): raise InterruptedError()
                    if time.monotonic()>end: raise RuntimeError('Tempo esgotado esperando '+step['scene'])
                continue
            self.execute(step,record=False)
        self.log('Rota concluída; aguardando próximo trecho.')
        return 'Rota concluída; aguardando próximo trecho.'
    def combat(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            frame,snap=self.observe()
            if snap['scene']!='jogo': self.log('Combate encerrou ao mudar de tela.'); return
            self.check(snap,True)
            target=self.enemy_target(frame)
            if target is None:
                self.log('Nenhuma barra de inimigo visível; combate encerrado.'); return
            h,w=frame.shape[:2]; dx=target[0]-.5*w; dy=target[1]-.5*h
            if math.hypot(dx,dy)>110:
                direction=('down' if dy>0 else 'up') if abs(dy)>abs(dx)*1.5 else ('right' if dx>0 else 'left') if abs(dx)>abs(dy)*1.5 else ('down' if dy>0 else 'up')+'_'+('right' if dx>0 else 'left')
                self.execute({'op':'move','direction':direction,'ms':min(450,max(100,int(math.hypot(dx,dy)*1.2))),'settle':.15},record=False)
            self.execute({'op':'attack','ms':1200,'settle':.15},record=False)
    @staticmethod
    def enemy_target(frame):
        h,w=frame.shape[:2]; hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,(0,160,85),(8,255,255))|cv2.inRange(hsv,(173,160,85),(180,255,255))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        candidates=[]
        for contour in contours:
            x,y,bw,bh=cv2.boundingRect(contour)
            if .20*w<x<.78*w and .13*h<y<.73*h and 35<=bw<=150 and 3<=bh<=14 and bw/bh>3:
                # A barra tem uma moldura escura. Isso exclui cabelo, roupa e efeitos vermelhos.
                top=frame[max(0,y-3):y,x:x+bw]
                bottom=frame[y+bh:min(h,y+bh+3),x:x+bw]
                if top.size and bottom.size and np.mean(np.max(top,axis=2)<85)>.55 and np.mean(np.max(bottom,axis=2)<85)>.55:
                    candidates.append((x+bw/2,y-25))
        return min(candidates,key=lambda p:math.hypot(p[0]-.5*w,p[1]-.5*h)) if candidates else None
    def worker(self):
        try:
            self.ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
            self.adb.connect(); self.observe(); self.mode='Pausado'; self.note='Pronto. Nenhuma rota executando.'
            self.log('Visão e ADB conectados.')
        except Exception as e: self.mode='Erro'; self.note=str(e); self.log(str(e))
        while not self.shutdown.is_set():
            try: job=self.jobs.get(timeout=2)
            except queue.Empty:
                try: self.observe()
                except Exception as e: self.note=str(e)
                continue
            self.busy=True; self.cancel.clear(); self.mode='Executando'
            try:
                result=None
                if job['type']=='action': self.execute(job['action'])
                elif job['type']=='combat': self.combat(10)
                elif job['type']=='route': result=self.route(job['name'])
                elif job['type']=='refresh': self.adb.connect(); self.observe()
                elif job['type']=='cognitive':
                    runtime=self.ensure_cognitive()
                    report=runtime.run(job.get('goal','Complete Guardian Tales Story'),job.get('max_cycles',8),job.get('max_seconds',180),self.cancel)
                    result='Agente: '+report['outcome']+'; decisão: '+str(report['decision'])
                    self.log(result)
                elif job['type']=='cognitive_inspect':
                    runtime=self.ensure_cognitive(); runtime.open_goal(job.get('goal','Complete Guardian Tales Story'))
                    observation=runtime.environment.observe(); runtime.evidence(observation); runtime.reconcile(observation)
                    runtime.memory.checkpoint(runtime.goal_id,observation,{'reason':'inspection_only'})
                    result='Estado atual registrado sem enviar comandos ao jogo.'
                elif job['type']=='record':
                    name=job['name']
                    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',name): raise ValueError('Use letras, números, _ ou -')
                    if (ROOT/'routes'/(name+'.json')).exists(): raise ValueError('Já existe uma rota com esse nome')
                    (ROOT/'routes'/name).mkdir(exist_ok=False)
                    self.recording=name; self.recorded=[]; self.save_recording(); self.log('Gravação iniciada: '+name)
                elif job['type']=='record_stop': self.log('Gravação salva.'); self.recording=None
                else: raise ValueError('Comando inválido')
                self.note=result or 'Ação concluída.'; self.mode='Pausado'
            except InterruptedError: self.note='Parado pelo usuário.'; self.mode='Pausado'
            except Exception as e:
                logging.exception('Execução interrompida'); self.note=str(e); self.mode='Revisar'; self.log(str(e))
            finally: self.busy=False; self.jobs.task_done()
    def status(self):
        routes=[]
        for p in (ROOT/'routes').glob('*.json'):
            try:
                data=json.loads(p.read_text(encoding='utf-8'))
                routes.append({'id':p.stem,'name':data.get('name',p.stem),'steps':len(data.get('steps',[])),'status':data.get('status','')})
            except (ValueError,OSError): continue
        with self.lock:
            return {'mode':self.mode,'note':self.note,'busy':self.busy,'pending':self.jobs.unfinished_tasks,'recording':self.recording,
                    'snapshot':self.snapshot,'events':list(self.events),'routes':routes,
                    'cognitive':self.cognition.status() if self.cognition else None,
                    'coverage':'Protótipo com rotas limitadas. História completa ainda não implementada.'}

BOT=Bot()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,data,kind='application/json; charset=utf-8',code=200):
        if not isinstance(data,bytes): data=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(code); self.send_header('Content-Type',kind); self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        try: self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError): pass
    def do_GET(self):
        path=self.path.split('?')[0]
        if path=='/': return self.send((ROOT/'panel.html').read_bytes().replace(b'__TOKEN__',TOKEN.encode()),'text/html; charset=utf-8')
        if path=='/status': return self.send(BOT.status())
        if path=='/frame.jpg':
            with BOT.lock: raw=BOT.jpeg
            return self.send(raw,'image/jpeg',200 if raw else 503)
        if path=='/knowledge': return self.send(json.loads((ROOT/'knowledge/worlds.json').read_text(encoding='utf-8')))
        return self.send({'error':'Não encontrado'},code=404)
    def do_POST(self):
        if self.headers.get('X-Bot-Token')!=TOKEN: return self.send({'error':'Acesso negado'},code=403)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<16384: raise ValueError('Requisição inválida')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict): raise ValueError('Comando deve ser um objeto JSON')
            if self.path=='/shutdown':
                BOT.cancel.set(); BOT.shutdown.set(); self.send({'ok':True})
                threading.Thread(target=SERVER.shutdown,daemon=True).start(); return
            if self.path=='/stop':
                BOT.cancel.set()
                while True:
                    try: BOT.jobs.get_nowait(); BOT.jobs.task_done()
                    except queue.Empty: break
                return self.send({'ok':True})
            if self.path!='/command': return self.send({'error':'Não encontrado'},code=404)
            if BOT.busy or not BOT.jobs.empty(): raise ValueError('Aguarde a ação atual ou pressione Parar')
            BOT.jobs.put_nowait(data); self.send({'ok':True})
        except Exception as e: self.send({'error':str(e)},code=400)

def main():
    global SERVER
    parser=argparse.ArgumentParser(); parser.add_argument('--no-browser',action='store_true'); parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler); SERVER=server
    worker_thread=threading.Thread(target=BOT.worker,daemon=True);worker_thread.start()
    url=f'http://127.0.0.1:{args.port}'
    print('Guardian Tales Bot — '+url,flush=True)
    if not args.no_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        BOT.cancel.set();BOT.shutdown.set();server.server_close();worker_thread.join(timeout=25)
        if not worker_thread.is_alive() and BOT.cognition:BOT.cognition.memory.close()
if __name__=='__main__': main()
