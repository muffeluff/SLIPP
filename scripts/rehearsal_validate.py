import json,datetime
from pathlib import Path
def read(p):return json.loads(Path(p).read_text())
def norm(s):return ''.join(c for c in s.casefold() if c.isalnum())
e=read('edition.json');g=read('genres.json');a=read('editorial/articles.json')['articles'];audit=read('singles-audit.json')
today=datetime.date.today().isoformat()
assert e['date']==today and audit['date']==today and audit['selected']==5, 'Fresh singles or edition missing'
assert len(g)==8 and len(e['mustListen']['albums'])==5 and len(e['mustListen']['singles'])==5
rows=[r for sections in g.values() for s in sections for r in s['items']]
assert all(s['items'] for sections in g.values() for s in sections), 'Empty genre'
assert len({(norm(r[0]),norm(r[1])) for r in rows})==len(rows), 'Duplicate albums'
reviews=[]
for r in rows:
    matches=[dict(source=x.get('source',x.get('sourceId','')),title=x['title'],url=x['url'],published=x['published'],verified=True,verification='editorial-feed-match') for x in a if x.get('kind')=='review' and x.get('published') and x.get('url','').startswith('https://') and norm(r[0]) in norm(x['title']) and norm(r[1]) in norm(x['title'])]
    reviews.append(dict(artist=r[0],title=r[1],articles=matches))
for r in rows+e['mustListen']['albums']+e['mustListen']['singles']:
    assert r[4].startswith('https://') and r[5]['releaseDate']<=today
Path('editorial/album-reviews.json').write_text(json.dumps(dict(updated=datetime.datetime.now(datetime.timezone.utc).isoformat(),releases=reviews),ensure_ascii=False,indent=2))
print('Validated',len(rows),'albums, five singles,',sum(len(r['articles']) for r in reviews),'feed-matched reviews')
