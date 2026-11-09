"""Fetch pinned official scrcpy server and protocol sources; verify publisher hash."""
from pathlib import Path
import concurrent.futures,hashlib,json,re,urllib.request
ROOT=Path(__file__).resolve().parents[2];VERSION='3.3.2'
BASE=f'https://raw.githubusercontent.com/Genymobile/scrcpy/v{VERSION}/'
folder=ROOT/'tools/scrcpy';folder.mkdir(parents=True,exist_ok=True)
research=ROOT/'data/v3/research';research.mkdir(parents=True,exist_ok=True)
def get(url):
    with urllib.request.urlopen(url,timeout=45) as response:return response.read()
installer=(research/'scrcpy-install_release.sh').read_bytes() if (research/'scrcpy-install_release.sh').exists() else get(BASE+'install_release.sh');(research/'scrcpy-install_release.sh').write_bytes(installer)
url=re.search(rb'PREBUILT_SERVER_URL=(\S+)',installer)[1].decode().strip('"')
expected=re.search(rb'PREBUILT_SERVER_SHA256=(\S+)',installer)[1].decode().strip('"')
binary=(folder/f'scrcpy-server-v{VERSION}').read_bytes() if (folder/f'scrcpy-server-v{VERSION}').exists() else get(url);actual=hashlib.sha256(binary).hexdigest()
if actual!=expected:raise RuntimeError('Official scrcpy server SHA256 mismatch')
(folder/f'scrcpy-server-v{VERSION}').write_bytes(binary)
tree=json.loads(get(f'https://api.github.com/repos/Genymobile/scrcpy/git/trees/v{VERSION}?recursive=1'))
connection=[f['path'] for f in tree['tree'] if f['path'].endswith('/DesktopConnection.java')]
if len(connection)!=1:raise RuntimeError('Official DesktopConnection source ambiguous')
files=['LICENSE','doc/develop.md','server/src/main/java/com/genymobile/scrcpy/control/ControlMessageReader.java','server/src/main/java/com/genymobile/scrcpy/control/Controller.java','server/src/main/java/com/genymobile/scrcpy/Options.java',connection[0]]
def source(path):
    destination=(folder/'LICENSE') if path=='LICENSE' else research/Path(path).name;data=destination.read_bytes() if destination.exists() else get(BASE+path);destination.write_bytes(data)
    return {'url':BASE+path,'path':str(destination.relative_to(ROOT)),'sha256':hashlib.sha256(data).hexdigest()}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:sources=list(pool.map(source,files))
manifest={'version':VERSION,'url':url,'sha256':actual,'bytes':len(binary),'verification_source':BASE+'install_release.sh','sources':sources,'purpose':'root-free persistent normal Android input; no game process or memory modification'}
(folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps({'version':VERSION,'sha256_verified':True,'bytes':len(binary),'sources':len(sources)}))
