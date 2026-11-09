from __future__ import annotations
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus, urlparse, urljoin
import hashlib, ipaddress, json, re, socket, time, urllib.request, xml.etree.ElementTree as ET
from .contracts import Provenance, now
from .perception import normalize

class TextExtractor(HTMLParser):
    def __init__(self): super().__init__(); self.hidden=0; self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript','svg'): self.hidden+=1
        if tag in ('p','li','h1','h2','h3','div','br'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript','svg'): self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden: self.parts.append(data)
    def text(self): return re.sub(r'[ \t]+',' ',' '.join(self.parts))

def public_url(url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443): raise ValueError('Only public HTTPS research URLs are allowed')
    try: addresses=[ipaddress.ip_address(parsed.hostname)]
    except ValueError: addresses=[ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)]
    if not addresses or any(not address.is_global for address in addresses): raise ValueError('Non-public research destination')
    return url

class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

class WebTransport:
    def fetch(self,url,timeout=8):
        public_url(url)
        request=urllib.request.Request(url,headers={'User-Agent':'GuardianTalesResearch/0.2 (read-only; bounded queries)'})
        opener=urllib.request.build_opener(PublicRedirect())
        with opener.open(request,timeout=timeout) as response:
            mime=response.headers.get_content_type()
            if mime not in ('text/html','text/plain','application/rss+xml','application/xml','text/xml','application/json'): raise ValueError('Unsupported research content: '+mime)
            body=response.read(786433)
            if len(body)>786432: raise ValueError('Research response exceeds size limit')
            return body.decode(response.headers.get_content_charset() or 'utf-8',errors='replace')

class ResearchEngine:
    """Bounded real HTTP discovery + excerpts. External content never becomes code."""
    def __init__(self,memory,library: Path,transport=None,max_requests=5):
        self.memory=memory; self.library=Path(library); self.transport=transport or WebTransport()
        self.max_requests=max_requests; self.requests=0; self.cache_hits=0
    def reset_budget(self): self.requests=0; self.cache_hits=0
    def fetch(self,url):
        key='http:'+hashlib.sha256(url.encode()).hexdigest()
        cached=self.memory.cached(key)
        if cached is not None: self.cache_hits+=1; return cached['body']
        if self.requests>=self.max_requests: raise RuntimeError('Research request budget exhausted')
        self.requests+=1
        body=self.transport.fetch(url)
        # Store only short responses in HTTP cache; source pages are reduced to
        # contextual excerpts by investigate, not mirrored in the database.
        if len(body)<16000: self.memory.cache(key,{'body':body},21600)
        return body
    @staticmethod
    def formulate(scope,problem):
        parts=scope.split(':')
        stage=(f'{parts[1]}-{parts[3]}' if len(parts)==4 else scope.replace(':',' '))
        kind='passage' if ':passage:' in scope else 'stage'
        return f'Guardian Tales "{stage}" {kind} '+problem[:100]+' walkthrough'
    def search(self,query):
        body=self.fetch('https://www.bing.com/search?format=rss&q='+quote_plus(query))
        root=ET.fromstring(body); out=[]
        for item in root.findall('./channel/item'):
            title=item.findtext('title',''); url=item.findtext('link',''); description=item.findtext('description','')
            relevant=normalize(title+' '+description+' '+url)
            if 'guardian' not in relevant or ('tales' not in relevant and 'guardiantales' not in relevant): continue
            if not url.startswith('https://'): continue
            out.append({'title':title[:200],'url':url,'snippet':description[:400],'source':'bing_rss','validation':'reported'})
            if len(out)==4: break
        return out
    def seeds(self,scope):
        if not self.library.exists(): return []
        data=json.loads(self.library.read_text(encoding='utf-8')); match=re.search(r'world:(\d+)',scope)
        if not match: return []
        worlds=[world for world in data.get('worlds',[]) if world['id']==int(match[1])]
        links=[]
        for world in worlds:
            for stage in world.get('stages',[]):
                for link in stage.get('links',[]):
                    url=link['url']
                    if 'youtube.com' not in url and 'results?' not in url:
                        links.append({'title':link['label'],'url':url,'snippet':'Curated reference; fetch needed','source':'local_catalog','validation':'reported'})
        # Prefer the article with actual stage links over inaccessible wiki pages.
        links.sort(key=lambda entry:('gamechosun' not in entry['url'],'blogspot' not in entry['url']))
        return list({entry['url']:entry for entry in links}.values())[:3]
    def investigate(self,scope,problem,goal_id=None):
        query=self.formulate(scope,problem); key='research:'+hashlib.sha256((scope+'|'+query).encode()).hexdigest()
        cached=self.memory.cached(key)
        if cached:
            self.cache_hits+=1; return {**cached,'cached':True}
        start=time.monotonic(); errors=[]; results=[]
        try: results=self.search(query)
        except Exception as error: errors.append(type(error).__name__+': '+str(error)[:180])
        candidates=results+self.seeds(scope); sources=[]; seen=set()
        for candidate in candidates:
            if candidate['url'] in seen: continue
            seen.add(candidate['url'])
            if len(sources)>=2: break
            if 'youtube.com' in candidate['url']:
                # Only a search snippet/link is available; no video understanding.
                sources.append({**candidate,'method':'search_snippet','confidence':.3}); continue
            try:
                body=self.fetch(candidate['url']); extractor=TextExtractor(); extractor.feed(body)
                lines=[line.strip() for line in extractor.text().splitlines() if len(line.strip())>30]
                tokens=set(re.findall(r'[a-z0-9]{3,}',normalize(query)))-{'guardian','tales','walkthrough','stage'}
                ranked=sorted(enumerate(lines),key=lambda pair:sum(t in normalize(pair[1]) for t in tokens),reverse=True)
                excerpt=' '.join(line for _,line in sorted(ranked[:3]))[:950]
                if len(excerpt)<40: raise ValueError('No usable text extracted')
                sources.append({**candidate,'snippet':excerpt,'method':'http_excerpt','confidence':.55,
                                'body_sha256':hashlib.sha256(body.encode()).hexdigest(),'retrieved_at':now()})
            except Exception as error: errors.append(candidate['url']+': '+str(error)[:140])
        result={'query':query,'scope':scope,'sources':sources,'errors':errors,'cached':False,
                'validation':'reported','contradictions':[], 'strategy':'Use as hypotheses; corroborate against the current screenshot before any action.',
                'requests':self.requests,'latency_ms':round((time.monotonic()-start)*1000,2)}
        if sources:
            self.memory.remember('semantic','research',scope,result,Provenance('research:http',method='search+extract'),.55,'reported',dedupe=key)
            self.memory.cache(key,result,86400)
        self.memory.remember('episodic','research_attempt',scope,{'query':query,'usable_sources':len(sources),'errors':errors,'goal_id':goal_id},Provenance('research:engine'),.95,'verified')
        return result
    @staticmethod
    def compare_claims(claims):
        groups={}
        for claim in claims:
            if not {'subject','property','value','source'}<=set(claim): continue
            key=(normalize(claim['subject']),normalize(claim['property']))
            groups.setdefault(key,[]).append(claim)
        return [{'subject':key[0],'property':key[1],'claims':items,'status':'disputed'} for key,items in groups.items()
                if len({normalize(str(item['value'])) for item in items})>1]
