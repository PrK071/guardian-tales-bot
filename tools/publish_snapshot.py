"""Upload snapshot bundles to this private repository using existing Git auth.

The credential is held only in memory and is never printed or written to disk.
Requires an existing commit pushed to main and locally packaged bundles.
"""
from pathlib import Path
import hashlib,http.client,json,os,subprocess,time,urllib.error,urllib.parse,urllib.request

ROOT=Path(__file__).resolve().parents[1];OWNER='PrK071';REPO='guardian-tales-bot';DATE='2026-11-09';TAG='snapshot-'+DATE

def main():
    output=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\nusername='+OWNER+'\n\n',text=True,capture_output=True,check=True,cwd=ROOT,env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'never'},creationflags=0x08000000)
    credential=dict(line.split('=',1) for line in output.stdout.splitlines() if '=' in line);token=credential['password']
    def api(method,path,data=None):
        request=urllib.request.Request('https://api.github.com'+path,method=method,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'GuardianTalesBot-Snapshot','X-GitHub-Api-Version':'2022-11-28'})
        with urllib.request.urlopen(request,timeout=45) as response:return json.load(response)
    if api('GET','/user')['login'].lower()!=OWNER.lower():raise RuntimeError('Authenticated account differs from requested owner')
    repository=api('GET',f'/repos/{OWNER}/{REPO}')
    if not repository['private']:raise RuntimeError('Workspace snapshot requires the private repository created for this task')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    manifests=[json.loads((ROOT/'publish'/DATE/(kind+'-manifest.json')).read_text()) for kind in ('runtime','evidence')]
    for manifest in manifests:
        path=ROOT/manifest['path']
        if not path.resolve().is_relative_to((ROOT/'publish').resolve()) or path.stat().st_size!=manifest['bytes']:raise RuntimeError('Snapshot bundle path/size mismatch')
    try:release=api('GET',f'/repos/{OWNER}/{REPO}/releases/tags/{TAG}')
    except urllib.error.HTTPError as error:
        if error.code!=404:raise
        body='Snapshot privado do trabalho até este commit. V3 em desenvolvimento; validação integral final pendente.\n\nExtraia os dois arquivos na raiz do projeto. Dados/capturas/SQLite e runtime/modelos ficam nos anexos para manter o Git leve.\n\nCommit: '+sha+'\n\n'+ '\n'.join(f"- `{m['name']}` — SHA256 `{m['sha256']}`" for m in manifests)
        release=api('POST',f'/repos/{OWNER}/{REPO}/releases',{'tag_name':TAG,'target_commitish':sha,'name':'Snapshot V3 em desenvolvimento — '+DATE,'body':body,'draft':False,'prerelease':True})
    assets=api('GET',f'/repos/{OWNER}/{REPO}/releases/{release["id"]}/assets');uploaded=[]
    for manifest in manifests:
        name=manifest['name'];existing=next((a for a in assets if a['name']==name),None)
        if existing:
            if existing['size']!=manifest['bytes'] or existing.get('state')!='uploaded':raise RuntimeError('Existing incomplete/different asset requires inspection: '+name)
            if existing.get('digest') and existing['digest']!='sha256:'+manifest['sha256']:raise RuntimeError('Existing asset digest mismatch: '+name)
            uploaded.append(existing);continue
        path=ROOT/manifest['path'];connection=http.client.HTTPSConnection('uploads.github.com',timeout=300)
        endpoint=f'/repos/{OWNER}/{REPO}/releases/{release["id"]}/assets?name='+urllib.parse.quote(name)
        connection.putrequest('POST',endpoint)
        for key,value in {'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'GuardianTalesBot-Snapshot','Content-Type':'application/zip','Content-Length':str(manifest['bytes'])}.items():connection.putheader(key,value)
        connection.endheaders();sent=0;last=time.monotonic();digest=hashlib.sha256()
        with path.open('rb') as file:
            while chunk:=file.read(4*1024*1024):
                connection.send(chunk);digest.update(chunk);sent+=len(chunk)
                if time.monotonic()-last>=15:print(json.dumps({'asset':name,'sent_bytes':sent,'total_bytes':manifest['bytes']}),flush=True);last=time.monotonic()
        response=connection.getresponse();result=json.loads(response.read());connection.close()
        if response.status!=201:raise RuntimeError('GitHub asset upload failed: '+str(response.status)+' '+str(result.get('message')))
        if digest.hexdigest()!=manifest['sha256'] or result['size']!=manifest['bytes']:raise RuntimeError('Uploaded asset differs from manifest')
        if result.get('digest') and result['digest']!='sha256:'+manifest['sha256']:raise RuntimeError('GitHub asset digest differs from manifest')
        uploaded.append(result);print(json.dumps({'asset':name,'uploaded':True,'bytes':result['size']}),flush=True)
    result={'repository':repository['html_url'],'private':repository['private'],'release':release['html_url'],'commit':sha,'assets':[{'name':a['name'],'bytes':a['size'],'url':a['browser_download_url'],'digest':a.get('digest')} for a in uploaded]}
    (ROOT/'publish'/DATE/'publication-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
