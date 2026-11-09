"""Package the existing local workspace without copying Git credentials."""
from pathlib import Path
import argparse,datetime,hashlib,json,time,zipfile

ROOT=Path(__file__).resolve().parents[1]
DATE='2026-11-09'

def package(kind):
    folders={'runtime':['tools','models'],'evidence':['data','captures','logs','backups']}[kind]
    destination=ROOT/'publish'/DATE;destination.mkdir(parents=True,exist_ok=True)
    path=destination/f'guardian-tales-{kind}-{DATE}.zip'
    paths=sorted(p for folder in folders for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo'))
    raw=sum(p.stat().st_size for p in paths);last=time.monotonic()
    with zipfile.ZipFile(path,'w',allowZip64=True) as archive:
        for index,item in enumerate(paths,1):
            compressed=item.suffix.lower() in ('.py','.json','.jsonl','.md','.txt','.html','.js','.cjs','.sqlite','.csv','.log')
            archive.write(item,item.relative_to(ROOT).as_posix(),compress_type=zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED,compresslevel=1 if compressed else None)
            if time.monotonic()-last>10:
                print(json.dumps({'bundle':kind,'files_done':index,'files_total':len(paths)}),flush=True);last=time.monotonic()
    digest=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
    result={'name':path.name,'path':str(path.relative_to(ROOT)),'bytes':path.stat().st_size,'sha256':digest,'files':len(paths),'uncompressed_bytes':raw,'folders':folders,'created_at':datetime.datetime.now().isoformat()}
    (destination/(kind+'-manifest.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('kind',choices=['runtime','evidence']);args=parser.parse_args();package(args.kind)
