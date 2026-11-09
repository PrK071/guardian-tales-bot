"""Install one verified PyPI wheel into the existing E: Python runtime."""
from pathlib import Path
import hashlib,json,sys,urllib.request,zipfile
ROOT=Path(__file__).resolve().parents[2]
version='19.0.2';name=f'av-{version}-cp312-abi3-win_amd64.whl'
meta=json.load(urllib.request.urlopen(f'https://pypi.org/pypi/av/{version}/json',timeout=20))
item=next(r for r in meta['urls'] if r['filename']==name)
folder=ROOT/'tools/wheels';folder.mkdir(exist_ok=True)
wheel=folder/name
if not wheel.exists():wheel.write_bytes(urllib.request.urlopen(item['url'],timeout=60).read())
digest=hashlib.sha256(wheel.read_bytes()).hexdigest()
if digest!=item['digests']['sha256']:raise RuntimeError('Wheel hash mismatch')
# This embedded runtime deliberately has no pip. The verified wheel has no
# install-time scripts or .data relocation; unpack it beside existing packages.
destination=ROOT/'tools/python/packages'
with zipfile.ZipFile(wheel) as archive:
    for info in archive.infolist():
        target=(destination/info.filename).resolve()
        if not target.is_relative_to(destination.resolve()) or '.data' in Path(info.filename).parts:raise RuntimeError('Unsupported wheel layout')
    archive.extractall(destination)
(folder/'av-manifest.json').write_text(json.dumps({'version':version,'filename':name,'sha256':digest,'source':item['url'],'purpose':'decode existing scrcpy video channel'},indent=2),encoding='utf-8')
