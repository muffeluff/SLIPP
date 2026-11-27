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
def verify(k):
    a,t=names[k]
    if re.search(r'remaster|anniversary|re.record|sped up|slowed|karaoke|live version',t,re.I):return
    for country in ['US','GB']:
        try:
            r=requests.get('https://itunes.apple.com/search',params=dict(term=a+' '+t,entity='song',country=country,limit=25),timeout=12);r.raise_for_status()
            rows=[x for x in r.json()['results'] if key(x.get('artistName',''),x.get('trackName',''))==k]
            if not rows:reject['no exact match']+=1;continue
            x=min(rows,key=lambda x:x.get('releaseDate','9999'))
            day=datetime.fromisoformat(x['releaseDate'].replace('Z','+00:00')).date()
            if day!=target:reject['wrong track date']+=1;continue
            if x.get('trackCount',99)>3 or not x.get('artworkUrl100'):reject['format or artwork']+=1;continue
            q=requests.get('https://itunes.apple.com/lookup',params={'id':x['collectionId'],'entity':'song','country':country},timeout=12);q.raise_for_status()
            col=next((y for y in q.json()['results'] if y.get('collectionType')=='Album'),{})
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
        except Exception as e:reject[type(e).__name__]+=1
# Rate-limit catalog queries and stop after enough verified candidates.
out=[];artists=set();checked=0
for k in ordered[:40]:
    if reject['HTTP 429']+reject['HTTP 403']>=3:break
    row=verify(k);checked+=1
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
Path('singles-audit.json').write_text(json.dumps(dict(date=str(today),sources=audit,checked=checked,selected=len(out),targetDate=str(target),rejections=dict(reject)),indent=2))
# Do not overwrite the previous edition on total failure.
if out or os.environ.get('SLIPP_RELEASE_DATE'):
    d.setdefault('mustListen',{})['singles']=out
    d['mustListen']['singlesDate']=str(today)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2))
print('Verified singles:',len(out), 'checked:',checked)
