"""Archive evidence changed since the published snapshot, with atomic SQLite backup."""
from pathlib import Path
import datetime,hashlib,json,sqlite3,time,zipfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    destination=ROOT/'publish/2026-11-09'
    base=json.loads((destination/'evidence-manifest.json').read_text())
    original=ROOT/base['path']
    if original.stat().st_size!=base['bytes']:raise RuntimeError('Base archive size differs from its published manifest')
    with zipfile.ZipFile(original) as archive:previous={item.filename:item for item in archive.infolist()}
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    path=destination/f'guardian-tales-evidence-delta-{stamp}.zip'
    database=destination/f'delta-sqlite-{stamp}.sqlite'
    source=sqlite3.connect((ROOT/'data/cognitive.sqlite').as_uri()+'?mode=ro',uri=True)
    target=sqlite3.connect(database)
    try:source.backup(target)
    finally:target.close();source.close()
    changed=[]
    for folder in ('data','captures','logs','backups'):
        for item in (ROOT/folder).rglob('*'):
            if not item.is_file() or '__pycache__' in item.parts or item.suffix in ('.pyc','.pyo') or item.name.endswith(('-journal','-wal','-shm')):continue
            name=item.relative_to(ROOT).as_posix()
            if name=='data/cognitive.sqlite':continue
            old=previous.get(name);stat=item.stat()
            if old and stat.st_size==old.file_size and stat.st_mtime<time.mktime(old.date_time+(0,0,-1))+2:continue
            changed.append((item,name))
    changed.append((database,'data/cognitive.sqlite'))
    with zipfile.ZipFile(path,'w',allowZip64=True) as archive:
        for item,name in sorted(changed,key=lambda pair:pair[1]):
            compressed=item.suffix.lower() in ('.py','.json','.jsonl','.md','.txt','.html','.js','.cjs','.sqlite','.csv','.log')
            archive.write(item,name,compress_type=zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED,compresslevel=1 if compressed else None)
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    result={'name':path.name,'path':str(path.relative_to(ROOT)),'bytes':path.stat().st_size,'sha256':digest,'files':len(changed),'base_asset':base['name'],'base_sha256':base['sha256'],'created_at':datetime.datetime.now().isoformat(),'sqlite_backup':'consistent SQLite backup; overlay after the base evidence archive','selection':'new paths or changed size/mtime; deletions are not propagated'}
    manifest=destination/f'delta-{stamp}-manifest.json';manifest.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'manifest':str(manifest.relative_to(ROOT)),**result}),flush=True)

if __name__=='__main__':main()
