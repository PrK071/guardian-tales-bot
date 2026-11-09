"""Console de calibração Android; registros e imagens ficam no disco E:."""
import sys, json, time, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parent
ADB = ROOT/'tools/platform-tools/adb.exe'
SERIAL = '127.0.0.1:5555'
def adb(*args):
    r = subprocess.run([str(ADB), '-s', SERIAL, *map(str,args)], capture_output=True, timeout=20)
    if r.returncode: raise RuntimeError(r.stderr.decode(errors='replace'))
    return r.stdout
def capture(name):
    p = ROOT/'captures'/f'{name}.png'
    p.write_bytes(adb('exec-out','screencap','-p'))
    return str(p)
if __name__=='__main__':
    args=sys.argv[1:]; stamp=str(time.time_ns()); before=capture(stamp+'-before')
    kind=args[0] if args else 'capture'
    if kind=='tap': adb('shell','input','tap',round(float(args[1])*1600),round(float(args[2])*900))
    elif kind=='swipe': adb('shell','input','swipe',*[round(float(args[i])*(1600 if i%2 else 900)) for i in range(1,5)],int(args[5]))
    elif kind=='key': adb('shell','input','keyevent',args[1])
    time.sleep(float(args[-1]) if kind=='wait' else 1.5)
    after=capture('latest')
    with (ROOT/'logs/calibration.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps({'time':time.time(),'args':args,'before':before,'after':capture(stamp+'-after')})+'\n')
    print(after)
