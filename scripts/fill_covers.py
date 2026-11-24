import json, time, urllib.request, urllib.parse, unicodedata
from pathlib import Path
def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',s.casefold()) if c.isalnum())
def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'SLIPP/1.0 (https://github.com/muffeluff/SLIPP)'})
    with urllib.request.urlopen(req,timeout=15) as r:
        return json.load(r)
def image(url):
    try:
        if not url.startswith('https://'): return False
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'SLIPP/1.0'}),timeout=15) as r:
            return r.headers.get_content_type().startswith('image/') and bool(r.read(32))
    except Exception: return False
def lookup(a,t):
    for entity in ('album','song'):
        try:
            time.sleep(3)
            q=urllib.parse.urlencode(dict(term=a+' '+t,entity=entity,country='US',limit=25))
            for x in get('https://itunes.apple.com/search?'+q).get('results',[]):
                if norm(x.get('artistName',''))==norm(a) and any(norm(x.get(k,''))==norm(t) for k in ('collectionName','trackName')):
                    u=x.get('artworkUrl100','')
                    if image(u): return u
        except Exception as e: print('iTunes:',e)
    try:
        time.sleep(1.2)
        q=urllib.parse.urlencode(dict(query='artist:"'+a.replace('"','')+'" AND releasegroup:"'+t.replace('"','')+'"',fmt='json',limit=10))
        for x in get('https://musicbrainz.org/ws/2/release-group/?'+q).get('release-groups',[]):
            artist=''.join(y.get('name','')+y.get('joinphrase','') for y in x.get('artist-credit',[]))
            if norm(artist)==norm(a) and norm(x['title'])==norm(t):
                u='https://coverartarchive.org/release-group/'+x['id']+'/front-500'
                if image(u): return u
    except Exception as e: print('MusicBrainz:',e)
    return ''
def rows(d):
    if 'sections' in d:
        for s in d['sections']: yield from s.get('items',[])
        for k in ('albums','singles'): yield from d.get('mustListen',{}).get(k,[])
    else:
        for sections in d.values():
            for s in sections: yield from s.get('items',[])
cache={}
for path in map(Path,['edition.json','genres.json']):
    d=json.loads(path.read_text())
    changed=False
    for p in rows(d):
        if not isinstance(p,list) or len(p)<2: continue
        key=tuple(p[:2])
        if len(p)>4 and p[4]: cache[key]=p[4]; continue
        if key not in cache: cache[key]=lookup(*key)
        u=cache[key]
        print(key, 'FOUND' if u else 'MISSING',flush=True)
        if u:
            while len(p)<5: p.append('')
            p[4]=u
            changed=True
    if changed: path.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
