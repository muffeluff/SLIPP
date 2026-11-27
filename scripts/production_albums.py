import json,requests,re,datetime,concurrent.futures,os
from zoneinfo import ZoneInfo
from pathlib import Path
def read(p):return json.loads(Path(p).read_text())
def write(p,d):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
today=datetime.datetime.now(ZoneInfo('Europe/Oslo')).date()
target=os.environ.get('SLIPP_RELEASE_DATE',str(today))
date=str(today)
start=str(datetime.date.fromisoformat(target)-datetime.timedelta(days=6))
pop=read('album-popularity.json')
old=read('edition.json')
oldg=read('genres.json')
archive=read('archive/index.json')
headers={'User-Agent':'SLIPP music catalog verification/1.0'}
def get(url,**kw):return requests.get(url,headers=headers,timeout=15,**kw)
def norm(s):return ''.join(c for c in s.casefold() if c.isalnum())
def excluded(title):
    return bool(re.search(r'\b(deluxe|edition|collection|compilation|remaster\w*|anniversary|greatest hits|archives?|demos?|live|concert|essentials|reissue|re-recorded)\b',title,re.I))
def check(a):
    if excluded(a['title']):return
    if re.search(r'\b(deluxe|edition|collection|compilation|remaster\w*|anniversary|single|EP|greatest hits|christmas|self covers)\b',a['title'],re.I) or a['artist']=='Various Artists':return
    for country in dict.fromkeys([s['country'] for s in a['signals']]+['us']):
        try:
            res=get('https://itunes.apple.com/lookup',params={'id':a['catalogId'],'country':country,'entity':'album'}).json()
            for x in res.get('results',[]):
                if x.get('collectionType')!='Album' or norm(x.get('artistName',''))!=norm(a['artist']) or norm(x.get('collectionName',''))!=norm(a['title']):continue
                if x.get('trackCount',0)<7:continue
                rd=x.get('releaseDate','')[:10]
                if not start<=rd<=target:continue
                art=x.get('artworkUrl100','')
                if not art:continue
                im=get(art,stream=True)
                ok=im.ok and im.headers.get('Content-Type','').startswith('image/')
                im.close()
                if not ok:continue
                return (a,x,rd,art)
        except Exception:continue
def diagnose(a):
    try:
        r=get(a['url'])
        return dict(url=a['url'],status=r.status_code,finalUrl=r.url,contentType=r.headers.get('Content-Type'),bytes=len(r.content),titlePresent=norm(a['title']) in norm(r.text),preview=re.sub(r'\s+',' ',r.text[:500]))
    except Exception as e:return dict(url=a['url'],error=str(e))
try:
    candidates=read('editorial/candidates.json')['articles']
except Exception as exc:
    print('Optional editorial candidates unavailable:',exc)
    candidates=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    diagnostics=list(pool.map(diagnose,candidates[:30]))
write('editorial/article-access-audit.json',dict(date=date,results=diagnostics))
# Merge independent catalog and editorial signals before selecting each genre.
try: articles=read('editorial/articles.json')['articles']
except Exception: articles=[]
def coverage(artist,title):
    if norm(artist)==norm(title) or len(norm(title))<4:return []
    return [dict(source=x.get('source',x.get('sourceId','')),title=x['title'],url=x['url'],published=x['published'],kind=x.get('kind'),verified=True,verification='editorial-feed-match') for x in articles if x.get('kind') in ('review','news','feature','interview') and x.get('published') and x.get('url','').startswith('https://') and norm(artist) in norm(x.get('title','')) and norm(title) in norm(x.get('title',''))]
def ranking(row,score,visibility):
    a=row[5]['articles']
    reviews=len({x['source'] for x in a if x['kind']=='review'})
    mentions=len({x['source'] for x in a if x['kind']!='review'})
    age=(datetime.date.fromisoformat(target)-datetime.date.fromisoformat(row[5]['releaseDate'])).days
    parts=dict(charts=40*min(score/1200,1),spotify=25*min(visibility/8,1),editorial=25*min((reviews+0.5*mentions)/3,1),freshness=10*(7-age)/7)
    row[5]['ranking']=parts
    return sum(parts.values())
def spotify():
    cid=os.getenv('SPOTIFY_CLIENT_ID');secret=os.getenv('SPOTIFY_CLIENT_SECRET')
    if not cid or not secret:return {}
    t=requests.post('https://accounts.spotify.com/api/token',auth=(cid,secret),data={'grant_type':'client_credentials'},timeout=20)
    t.raise_for_status()
    session=requests.Session();session.headers['Authorization']='Bearer '+t.json()['access_token']
    import time
    found={}
    for market in ['US','GB','NO','DE','SE','FR','CA','AU']:
        for offset in [0,10,20]:
            time.sleep(2)
            res=session.get('https://api.spotify.com/v1/search',params=dict(q='tag:new year:'+target[:4],type='album',market=market,limit=10,offset=offset),timeout=20)
            if res.status_code==429:return found
            if not res.ok:continue
            for a in (res.json().get('albums') or {}).get('items',[]):
                if not a or a.get('album_type')!='album' or a.get('total_tracks',0)<7 or a.get('release_date_precision')!='day' or not start<=a.get('release_date','')<=target:continue
                artist=', '.join(x['name'] for x in a['artists']);title=a['name']
                if excluded(title) or artist=='Various Artists' or re.search(r'\b(deluxe|edition|collection|compilation|remaster\w*|anniversary|greatest hits)\b',title,re.I):continue
                k=norm(artist)+'|'+norm(title)
                e=found.setdefault(k,dict(album=a,markets=set(),artist=artist,title=title))
                e['markets'].add(market)
    # Resolve genre via independent Apple catalog matches; no editorial requirement.
    for e in found.values():
        try:
            time.sleep(2)
            res=get('https://itunes.apple.com/search',params=dict(term=e['artist']+' '+e['title'],entity='album',country='US',limit=15))
            if res.status_code in (403,429):break
            for x in res.json().get('results',[]):
                if norm(x.get('artistName',''))==norm(e['artist']) and norm(x.get('collectionName',''))==norm(e['title']) and start<=x.get('releaseDate','')[:10]<=target:
                    e['genre']=x.get('primaryGenreName','');break
        except Exception:continue
    return found
try: sp=spotify()
except Exception as exc:
    print('Spotify discovery unavailable:',type(exc).__name__);sp={}
print('Spotify album candidates:',len(sp),'window:',start,target)
def genre_of(s):
    for g,p in [('Metal','metal'),('Hip-hop','hip.hop|rap'),('Elektronisk','electronic|dance|house|techno|ambient'),('Country','country|americana|bluegrass'),('Jazz','jazz'),('Indie','alternative|indie'),('Rock','rock'),('Pop','pop')]:
        if re.search(p,s,re.I):return g
    return None
genres={}
seen=set()
seen_ids=set()
seen_titles=set()
def duplicate(row):
    title=norm(row[1]);artist=norm(row[0])
    # Cross-script localized artist names with identical titles are conservatively merged.
    return any(t==title and (a==artist or (a.isascii()!=artist.isascii())) for a,t in seen_titles) or bool(row[5].get('catalogId') and row[5]['catalogId'] in seen_ids)
ranked=[]
for genre in ['Indie','Rock','Pop','Hip-hop','Country','Jazz','Metal','Elektronisk']:
    items=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(check,[a for a in pop['genres'][genre] if not a.get('releaseDate') or start<=a['releaseDate']<=target][:60]))
    for result in results:
        if not result:continue
        a,x,rd,art=result
        key=norm(a['artist'])+'|'+norm(a['title'])
        if key in seen:continue
        primary=x.get('primaryGenreName','')
        if genre=='Rock' and re.search('metal',primary,re.I):continue
        if genre=='Elektronisk' and not re.search('electronic|dance|house|techno|ambient',primary,re.I):continue
        row=[a['artist'],a['title'],primary or genre,'',art,dict(releaseDate=rd,label='Populært nå',articles=[],signals=a['signals'],catalogUrl=x.get('collectionViewUrl',''),catalogId=str(a['catalogId']))]
        row[5]['articles']=coverage(*row[:2])
        entry=sp.get(key)
        if entry:
            row[5]['spotifyUrl']=entry['album'].get('external_urls',{}).get('spotify','')
        items.append((ranking(row,a['score'],len(entry['markets']) if entry else 0),row))
    # Spotify-only albums need independent genre evidence from exact editorial matches.
    for k,entry in sp.items():
        if k in seen or any(norm(r[0])+'|'+norm(r[1])==k for _,r in items):continue
        a=entry['album'];artist=entry['artist'];title=entry['title']
        matched=coverage(artist,title)
        source_urls={x['url'] for x in matched}
        if genre_of(entry.get('genre',''))!=genre and not any(x.get('url') in source_urls and genre.casefold() in [str(g).casefold() for g in x.get('genres',[])] for x in articles):continue
        art=(a.get('images') or [{}])[0].get('url','')
        if not art:continue
        try:
            im=get(art,stream=True);ok=im.ok and im.headers.get('Content-Type','').startswith('image/');im.close()
            if not ok:continue
        except Exception:continue
        row=[artist,title,genre,'',art,dict(releaseDate=a['release_date'],articles=matched,signals=[],spotifyUrl=a.get('external_urls',{}).get('spotify',''),verification='Spotify')]
        items.append((ranking(row,0,len(entry['markets'])),row))
    selected=[]
    for score,row in sorted(items,key=lambda x:x[0],reverse=True):
        if duplicate(row):continue
        seen_titles.add((norm(row[0]),norm(row[1])))
        if row[5].get('catalogId'):seen_ids.add(row[5]['catalogId'])
        seen.add(norm(row[0])+'|'+norm(row[1]));ranked.append((score,row));selected.append(row)
        if len(selected)==5:break
    items=selected
    genres[genre]=[dict(source='SLIPP',title='Ukens album',date=date,items=items)]
if not ranked:raise RuntimeError('No verified catalog results; existing edition preserved')
stamp=old['date']
ep='archive/'+stamp+'-pretest.json'
gp='archive/'+stamp+'-pretest-genres.json'
if not Path(ep).exists():
    write(ep,old);write(gp,oldg)
    if not any(a['date']==stamp for a in archive):archive.append(dict(date=stamp,edition=ep,genres=gp))
    write('archive/index.json',archive)
new=dict(date=date,sections=[dict(s[0],title=g+' · Ukens album') for g,s in genres.items()],mustListen=dict(date=date,method='Ukens nye album: redaksjonell omtale, iTunes og Spotify',albums=[r for _,r in sorted(ranked,key=lambda x:x[0],reverse=True)[:5]],singles=old.get('mustListen',{}).get('singles',[])))
write('genres.json',genres);write('edition.json',new)
print({g:len(s[0]['items']) for g,s in genres.items()})