import json, requests, feedparser, re, calendar
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
now=datetime.now(timezone.utc)
stamp=now.isoformat()
root=Path('editorial')
root.mkdir(exist_ok=True)
sources=json.load(open('source-audit.json'))['sources']
def canonical(url):
    p=urlsplit(url)
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode([(k,v) for k,v in parse_qsl(p.query) if not k.startswith('utm_')]),''))
def classify(source,title,url,tags):
    signal=' '.join([title,url,*tags]).lower()
    path=urlsplit(url).path.lower()
    if re.search(r'product-recommendations|film-reviews|tv-reviews|book-reviews|live-reviews|concert-review|/interviews?/|/fashion/|/politics/|/tv-movies/|/lifestyle/',path): return 'other'
    if re.search(r'\b(concert review|live review|tour dates|announces? (a |new |final )?tour|live residency|festival lineup|film review|movie review|book review|in conversation|interview|magnesium supplements|car accident|wedding|has passed away|has died)\b',title.lower()): return 'other'
    if re.search(r'\b(at|live at)\b.*\b(jazz club|cadogan hall|festival|arena)\b|\bEFG LJF\b',title,re.I): return 'other'
    if source=='pitchfork.com' and '/reviews/albums/' in path: return 'review'
    if re.search(r'album.review|track.review|single.review|ep.review|record.review|/reviews/albums/|/reviews/tracks/|/quietus-reviews/|/reviews/premature-evaluation/|album-of-the-day|/music/reviews/',signal): return 'review'
    if source=='angrymetalguy.com' and re.search(r'\breview\b',title,re.I): return 'review'
    if re.search(r'\b(track premiere|song premiere|single premiere|album premiere|ep premiere|first listen)\b',signal): return 'premiere'
    if re.search(r'best (new )?(albums|songs|tracks|singles|eps|music|releases)|albums.of.the.week|tracks.of.the.week|songs.of.the.week|new music friday|best-(ambient|house|techno|jazz|metal|electronic|country|hip-hop|field-recordings|contemporary-classical)',signal): return 'recommendation'
    if source=='acloserlisten.com' and ' ~ ' in title: return 'review'
    return 'other'
def collect(s):
    if not s.get('feed'): return s['id'],[], 'no_feed'
    try:
        response=requests.get(s['feed'],timeout=20,headers={'User-Agent':'SLIPP editorial index/1.0'})
        response.raise_for_status()
        feed=feedparser.parse(response.content)
        if not feed.entries: raise ValueError('Empty feed')
        rows=[]
        for x in feed.entries:
            url=canonical(x.get('link',''))
            if not url.startswith(('https://','http://')): continue
            title=x.get('title','')
            tags=[t.get('term','') for t in x.get('tags',[])]
            signal=' '.join([title,url,*tags]).lower()
            kind=classify(s['id'],title,url,tags)
            date=x.get('published_parsed') or x.get('updated_parsed')
            published=datetime.fromtimestamp(calendar.timegm(date),timezone.utc).isoformat() if date else None
            rows.append(dict(source=s['name'],sourceId=s['id'],sourceType=s['type'],genres=s['genres'],title=title,url=url,tags=tags,published=published,firstSeen=stamp,kind=kind,verification='pending',excerpt=BeautifulSoup(x.get('summary',''),'html.parser').get_text(' ',strip=True)[:400]))
        return s['id'],rows,'ok'
    except Exception as e: return s['id'],[],str(e)
with ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(collect,sources))
path=root/'articles.json'
old=json.loads(path.read_text())['articles'] if path.exists() else []
merged={(x['sourceId'],x['url']):x for x in old}
for sid,rows,status in results:
    for row in rows:
        key=(sid,row['url'])
        if key in merged: row['firstSeen']=merged[key]['firstSeen']
        merged[key]=row
for row in merged.values():
    row['kind']=classify(row['sourceId'],row['title'],row['url'],row.get('tags',[]))
cutoff=(now-timedelta(days=60)).isoformat()
articles=sorted([x for x in merged.values() if x['firstSeen']>=cutoff],key=lambda x:x['published'] or x['firstSeen'],reverse=True)
path.write_text(json.dumps(dict(updated=stamp,articles=articles),ensure_ascii=False,indent=2))
candidates=[x for x in articles if x['kind'] in ('review','premiere','recommendation') and x['published'] and x['published']>=(now-timedelta(days=7)).isoformat()]
(root/'candidates.json').write_text(json.dumps(dict(updated=stamp,articles=candidates),ensure_ascii=False,indent=2))
(root/'status.json').write_text(json.dumps(dict(updated=stamp,total=len(articles),candidates=len(candidates),sources=[dict(id=sid,count=len(rows),status=status) for sid,rows,status in results]),ensure_ascii=False,indent=2))