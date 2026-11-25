import json,datetime,os
from zoneinfo import ZoneInfo
from pathlib import Path
def read(p):return json.loads(Path(p).read_text())
def norm(s):return ''.join(c for c in s.casefold() if c.isalnum())
e=read('edition.json');g=read('genres.json');audit=read('singles-audit.json')
today=datetime.datetime.now(ZoneInfo('Europe/Oslo')).date().isoformat()
target=os.environ['SLIPP_RELEASE_DATE']
print('Edition date:',e['date'],'Audit date:',audit['date'],'Expected:',today,'Fresh singles:',audit['selected'],flush=True)
print('Singles source coverage:',json.dumps(audit['sources']),flush=True)
assert e['date']==today, 'Edition date mismatch'
assert audit['date']==today, 'Singles audit date mismatch'
assert audit['targetDate']==target
assert 1<=audit['selected']<=5, 'No verified Friday singles; refusing stale fallback'
assert all(r[5]['releaseDate']==target for r in e['mustListen']['singles'])
assert len(g)==8 and 1<=len(e['mustListen']['albums'])<=5 and len(e['mustListen']['singles'])==audit['selected']
rows=[r for sections in g.values() for s in sections for r in s['items']]
assert all(len(s['items'])<=5 for sections in g.values() for s in sections)
print('Friday album coverage:',{k:sum(len(s['items']) for s in v) for k,v in g.items()})
assert len({(norm(r[0]),norm(r[1])) for r in rows})==len(rows), 'Duplicate albums'
try:
    a=read('editorial/articles.json')['articles']
except Exception as exc:
    print('Optional editorial data unavailable:',exc)
    a=[]
reviews=[]
for r in rows+e['mustListen']['singles']:
    matches=[dict(source=x.get('source',x.get('sourceId','')),title=x['title'],url=x['url'],published=x['published'],verified=True,verification='editorial-feed-match') for x in a if x.get('kind')=='review' and x.get('published') and x.get('url','').startswith('https://') and norm(r[0]) in norm(x['title']) and norm(r[1]) in norm(x['title'])]
    reviews.append(dict(artist=r[0],title=r[1],articles=matches))
for r in rows+e['mustListen']['albums']+e['mustListen']['singles']:
    assert r[4].startswith('https://') and r[5]['releaseDate']==target
Path('editorial/album-reviews.json').write_text(json.dumps(dict(updated=datetime.datetime.now(datetime.timezone.utc).isoformat(),releases=reviews),ensure_ascii=False,indent=2))
print('Validated',len(rows),'albums,',audit['selected'],'Friday singles,',sum(len(r['articles']) for r in reviews),'feed-matched reviews')
