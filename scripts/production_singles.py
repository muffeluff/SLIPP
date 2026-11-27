import json, re, unicodedata, requests, time, os
from collections import Counter
from zoneinfo import ZoneInfo
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
today=datetime.now(ZoneInfo('Europe/Oslo')).date()
target=datetime.fromisoformat(os.environ.get('SLIPP_RELEASE_DATE',str(today))).date()
reject=Counter()
def norm(s): return ''.join(c for c in unicodedata.normalize('NFKC',s).casefold() if c.isalnum())
def key(a,t): return norm(a),norm(t)
signals=defaultdict(list); names={}; audit={}
seed_path=Path('editorial/single-discovery.json')
if seed_path.exists():
    seeds=json.loads(seed_path.read_text())
else: seeds={}
def add(a,t,p,rank,url,apple=False):
    k=key(a,t)
    if not all(k) or not 1<=rank<=200:return
    names[k]=(a,t)
    signals[k].append(dict(source=p,rank=rank,url=url,apple=apple))
def get(url):
    for attempt in range(3):
        try:
            r=requests.get(url,timeout=15,headers={'User-Agent':'Mozilla/5.0'})
            if r.status_code not in (429,500,502,503,504):return r
        except requests.RequestException:
            if attempt==2:raise
        time.sleep(1+attempt)
    return r
for c in ['us','gb','no','se','de','fr','jp','au','ca','nl']:
    url=f'https://rss.marketingtools.apple.com/api/v2/{c}/music/most-played/100/songs.json'
    try:
        r=get(url);r.raise_for_status()
        rows=r.json()['feed']['results']
        for i,x in enumerate(rows,1):add(x['artistName'],x['name'],'Apple Music',i,url,True)
        audit[url]=len(rows)
    except Exception as e:audit[url]=str(e)
# Discover recent purchases independently of streaming chart placement.
for c in ['us','gb','no','se','de','fr','jp','au','ca','nl']:
    url=f'https://itunes.apple.com/{c}/rss/topsongs/limit=100/json'
    try:
        r=get(url);r.raise_for_status()
        rows=r.json()['feed'].get('entry',[])
        if isinstance(rows,dict):rows=[rows]
        for i,x in enumerate(rows,1):
            if x.get('im:releaseDate',{}).get('label','')[:10]==str(target):
                add(x['im:artist']['label'],x['im:name']['label'],'iTunes purchases',i,url,True)
        audit[url]=len(rows)
    except Exception as e:audit[url]=str(e)
for provider,url in [('Official Charts','https://www.officialcharts.com/charts/singles-chart/'),('Billboard','https://ca.billboard.com/charts/billboard-global-200')]:
    try:
        r=get(url);r.raise_for_status();s=BeautifulSoup(r.text,'html.parser');n=0
        if provider=='Official Charts':
            for row in s.select('.chart-item'):
                a=row.select_one('.artist');t=row.select_one('.title');rank=row.select_one('.position')
                if a and t and rank and rank.get_text(strip=True).isdigit():
                    add(a.get_text(strip=True),t.get_text(strip=True),provider,int(rank.get_text(strip=True)),url);n+=1
        else:
            for row in s.select('.o-chart-results-list-row-container'):
                t=row.select_one('h3');a=row.select_one('h3 + span');rank=row.select_one('.c-label')
                if a and t and rank and rank.get_text(strip=True).isdigit():
                    add(a.get_text(strip=True),t.get_text(strip=True),provider,int(rank.get_text(strip=True)),url);n+=1
        audit[url]=n
    except Exception as e:audit[url]=str(e)
# Spotify chart access is not assumed; add only when an official CSV endpoint is accessible.
url='https://charts.spotify.com/charts/view/regional-global-daily/latest'
audit[url]='not integrated: authenticated chart download required'
# Dated editorial discovery candidates are supplied by public search, not page scraping.
if seeds.get('date')==str(target):
    for i,x in enumerate(seeds.get('items',[])[:40],1):
        add(x['artist'],x['title'],'New release discovery',i,x['url'])
    audit['editorial/single-discovery.json']=len(seeds.get('items',[]))
def score(k):
    ss=signals[k];others={x['source'] for x in ss if not x['apple']}
    best={p:min(x['rank'] for x in ss if x['source']==p) for p in others}
    return (len(others),sum(201-r for r in best.values()),sum(101-x['rank'] for x in ss if x['apple']))
ordered=sorted(names,key=lambda k:(any(x['source'] in ('New release discovery','iTunes purchases') for x in signals[k]),score(k)),reverse=True)
last_catalog=0
apple_blocked=False
details=[]
def catalog(url,params):
    global last_catalog,apple_blocked
    time.sleep(max(0,5-(time.monotonic()-last_catalog)))
    last_catalog=time.monotonic()
    r=requests.get(url,params=params,timeout=15,headers={'User-Agent':'SLIPP/1.0 (https://github.com/muffeluff/SLIPP)'})
    if 'itunes.apple.com' in url and r.status_code in (403,429):
        apple_blocked=True
    r.raise_for_status()
    return r.json()
def verify_mb(k):
    a,t=names[k]
    try:
        esc=lambda s:s.replace(chr(92),chr(92)*2).replace('"',chr(92)+'"')
        data=catalog('https://musicbrainz.org/ws/2/release-group',dict(query=f'artist:"{esc(a)}" AND releasegroup:"{esc(t)}" AND primarytype:single',fmt='json',limit=20))
        for x in data.get('release-groups',[]):
            artist=''.join(y.get('name',y.get('artist',{}).get('name',''))+y.get('joinphrase','') for y in x.get('artist-credit',[]))
            if key(artist,x.get('title',''))!=k or x.get('primary-type')!='Single' or x.get('first-release-date')!=str(target):continue
            if x.get('secondary-types'):continue
            releases=catalog('https://musicbrainz.org/ws/2/release-group/'+x['id'],dict(inc='releases',fmt='json')).get('releases',[])
            if any(y.get('date','') and y['date']<str(target) for y in releases):continue
            for y in releases:
                if y.get('date')!=str(target) or y.get('status')!='Official':continue
                url='https://coverartarchive.org/release/'+y['id']+'/front-500'
                im=requests.get(url,timeout=15)
                if im.ok and im.headers.get('Content-Type','').startswith('image/'):
                    return [a,t,'','',url,dict(releaseDate=str(target),articles=[],signals=signals[k],verification='MusicBrainz',releaseGroupId=x['id'])]
        reject['MusicBrainz no verified single with artwork']+=1
    except requests.HTTPError as e:reject['MusicBrainz HTTP '+str(e.response.status_code if e.response is not None else 0)]+=1
    except Exception as e:reject['MusicBrainz '+type(e).__name__]+=1
def verify_apple(k):
    a,t=names[k]
    if re.search(r'remaster|anniversary|re.record|sped up|slowed|karaoke|live version',t,re.I):return
    for country in ['US','GB']:
        if apple_blocked:break
        try:
            data=catalog('https://itunes.apple.com/search',dict(term=a+' '+t,entity='song',country=country,limit=25))
            rows=[x for x in data.get('results',[]) if key(x.get('artistName',''),x.get('trackName',''))==k and x.get('releaseDate') and x.get('collectionId')]
            if not rows:reject['no exact match']+=1;continue
            x=min(rows,key=lambda x:x.get('releaseDate','9999'))
            day=datetime.fromisoformat(x['releaseDate'].replace('Z','+00:00')).date()
            if day!=target:reject['wrong track date']+=1;continue
            if x.get('trackCount',99)>3 or not x.get('artworkUrl100'):reject['format or artwork']+=1;continue
            q=catalog('https://itunes.apple.com/lookup',{'id':x['collectionId'],'entity':'song','country':country})
            col=next((y for y in q.get('results',[]) if y.get('collectionType')=='Album' and y.get('releaseDate')),{})
            if not col or not re.search(r'\bSingle$',col.get('collectionName',''),re.I):reject['not single']+=1;continue
            if datetime.fromisoformat(col['releaseDate'].replace('Z','+00:00')).date()!=target:reject['wrong collection date']+=1;continue
            im=get(x['artworkUrl100'])
            if not im.ok or not im.headers.get('Content-Type','').startswith('image/'):reject['invalid artwork']+=1;continue
            return [x['artistName'],x['trackName'],x.get('primaryGenreName',''),'',x['artworkUrl100'],dict(releaseDate=str(day),articles=[],signals=signals[k])]
        except requests.HTTPError as e:
            status=e.response.status_code if e.response is not None else 0
            reject['HTTP '+str(status)]+=1
            if status in (403,429):
                time.sleep(3)
                return
        except Exception as e:reject[type(e).__name__+': '+str(e)[:120]]+=1
# Spotify catalog: bounded discovery, exact day, track history and artwork.
def spotify_candidates():
    cid=os.environ.get('SPOTIFY_CLIENT_ID'); secret=os.environ.get('SPOTIFY_CLIENT_SECRET')
    if not cid or not secret:
        audit['Spotify']='credentials unavailable';return []
    token=requests.post('https://accounts.spotify.com/api/token',auth=(cid,secret),data={'grant_type':'client_credentials'},timeout=20)
    audit['Spotify token']=token.status_code
    if not token.ok:return []
    session=requests.Session();session.headers['Authorization']='Bearer '+token.json()['access_token']
    blocked=False
    def api(path,**params):
        nonlocal blocked
        if blocked:return {}
        time.sleep(2)
        r=session.get('https://api.spotify.com/v1/'+path,params=params,timeout=20)
        if r.status_code==429:blocked=True
        if not r.ok:
            reject['Spotify HTTP '+str(r.status_code)]+=1;return {}
        return r.json()
    candidates={}
    def collect(q,market,offset=0,expected=None):
        data=api('search',q=q,type='album',market=market,limit=10,offset=offset)
        for rank,a in enumerate((data.get('albums') or {}).get('items',[]),offset+1):
            if not a:continue
            artist=', '.join(x['name'] for x in a.get('artists',[]))
            title=a.get('name','')
            if expected and (norm(title)!=norm(expected['title']) or norm(expected['artist']) not in [norm(x['name']) for x in a.get('artists',[])]):continue
            if a.get('release_date')!=str(target) or a.get('release_date_precision')!='day' or a.get('album_type')!='single' or not 1<=a.get('total_tracks',0)<=3:continue
            if re.search(r'remaster|anniversary|re.record|sped up|slowed|karaoke|live version|unwrapped',title,re.I):continue
            k=key(artist,title)
            entry=candidates.setdefault(k,dict(album=a,markets=set(),editorial=False,rank=rank))
            entry['markets'].add(market);entry['editorial']|=bool(expected);entry['rank']=min(entry['rank'],rank)
    for market in ['US','GB','NO','DE','SE','FR','CA','AU']:
        for offset in [0,10]:collect('tag:new year:'+str(target.year),market,offset)
    if seeds.get('date')==str(target):
        for x in seeds.get('items',[])[:20]:collect('artist:'+x['artist']+' album:'+x['title'],'US',expected=x)
    audit['Spotify candidates']=len(candidates)
    def priority(item):
        k,e=item
        return (score(k),e['editorial'],len(e['markets']),-e['rank'])
    rows=[]
    for k,e in sorted(candidates.items(),key=priority,reverse=True)[:25]:
        a=e['album'];artist=', '.join(x['name'] for x in a['artists']);title=a['name']
        tracks=api('albums/'+a['id']+'/tracks',limit=10).get('items',[])
        matching=[t for t in tracks if norm(t.get('name',''))==norm(title)]
        reason='no exact title track'
        if matching:
            t=matching[0]
            history=api('search',q='artist:'+a['artists'][0]['name']+' track:'+title,type='track',market='US',limit=10)
            matches=[x for x in (history.get('tracks') or {}).get('items',[]) if x and norm(x.get('name',''))==norm(title) and any(norm(y.get('name',''))==norm(a['artists'][0]['name']) for y in x.get('artists',[]))]
            dates=[x.get('album',{}).get('release_date','') for x in matches]
            reason='older release or unavailable track history'
            if dates and all(d and d>=str(target) for d in dates) and str(target) in dates:
                cover=(a.get('images') or [{}])[0].get('url');url=(t.get('external_urls') or {}).get('spotify')
                reason='missing or invalid artwork/link'
                if cover and url:
                    im=get(cover)
                    if im.ok and im.headers.get('Content-Type','').startswith('image/'):
                        rows.append([artist,title,'','',cover,dict(releaseDate=str(target),articles=[],signals=signals[k],verification='Spotify',spotifyUrl=url,spotifyAlbumId=a['id'])])
                        reason='verified'
        details.append(dict(artist=artist,title=title,verified=reason=='verified',reason=reason))
        print(json.dumps(details[-1],ensure_ascii=False),flush=True)
        if len(rows)>=5:break
    return rows

# Rate-limit catalog queries and stop after enough verified candidates.
out=[];artists=set();checked=0
try:
    for row in spotify_candidates():
        if norm(row[0]) not in artists:out.append(row);artists.add(norm(row[0]))
except Exception as e:audit['Spotify error']=type(e).__name__
checked=len(details)
for k in ordered[:40]:
    if len(out)>=5:break
    if not any(x['source'] in ('New release discovery','iTunes purchases') for x in signals[k]):continue
    before=reject.copy()
    row=verify_apple(k) or verify_mb(k);checked+=1
    details.append(dict(artist=names[k][0],title=names[k][1],verified=bool(row),rejections=dict(reject-before)))
    print(json.dumps(details[-1],ensure_ascii=False),flush=True)
    if row and norm(row[0]) not in artists:
        artists.add(norm(row[0]));out.append(row)
    if len(out)>=5:break
    time.sleep(.35)
p=Path('edition.json');d=json.loads(p.read_text())
# Only attach reviews explicitly verified by editorial research, never mere catalog matches.
try:
    reviews=json.loads(Path('editorial/verified-releases.json').read_text())['releases']
    for row in out:
        row[5]['articles']=[a for x in reviews if key(x['artist'],x['title'])==key(*row[:2]) and x.get('format') in ('single','song','track') for a in x.get('articles',[]) if a.get('verified') is True]
except Exception:pass
Path('singles-audit.json').write_text(json.dumps(dict(date=str(today),sources=audit,checked=checked,selected=len(out),targetDate=str(target),rejections=dict(reject),details=details),indent=2))
# Do not overwrite the previous edition on total failure.
if out or os.environ.get('SLIPP_RELEASE_DATE'):
    d.setdefault('mustListen',{})['singles']=out
    d['mustListen']['singlesDate']=str(today)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2))
print('Verified singles:',len(out), 'checked:',checked)
