import datetime as dt, json, re, unicodedata, os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

GENRES={'Breakbeat':1044,'Garage':1046,'Hardcore':1047,'House':1048,'Jungle/Drum & Bass':1049,'Techno':1050,'Trance':1051,'Ambient':1056,'Downtempo':1057,'Electronica':1058,'IDM/Experimental':1060,'Industrial':1061,'Dubstep':100014,'Bass':100015}
COUNTRIES=['us','gb','no','se','de','fr','jp','au']
today=dt.datetime.now(ZoneInfo('Europe/Oslo')).date()
end=dt.date.fromisoformat(os.environ.get('SLIPP_RELEASE_DATE') or str(today-dt.timedelta(days=(today.weekday()-4)%7)))
start=end-dt.timedelta(days=6)
def norm(s):
    return ' '.join(re.findall(r'\w+',unicodedata.normalize('NFKC',s or '').casefold()))
def label(x,k): return x.get(k,{}).get('label','')
def fetch(job):
    genre,gid,country=job
    url=f'https://itunes.apple.com/{country}/rss/topalbums/limit=100/genre={gid}/json'
    try:
        r=requests.get(url,timeout=25);r.raise_for_status()
        entries=r.json()['feed'].get('entry',[])
        if isinstance(entries,dict): entries=[entries]
        rows=[]
        for rank,x in enumerate(entries,1):
            artist,title,date=label(x,'im:artist'),label(x,'im:name'),label(x,'im:releaseDate')[:10]
            category=x.get('category',{}).get('attributes',{})
            if str(category.get('im:id'))!=str(gid): continue
            if not artist or not title or not str(start)<=date<=str(end): continue
            if re.search(r'\b(remaster\w*|anniversary|greatest hits|reissue)\b',title,re.I): continue
            link=x.get('link',{})
            if isinstance(link,list): link=link[0] if link else {}
            url2=link.get('attributes',{}).get('href','')
            if not url2.startswith('https://'): continue
            images=x.get('im:image',[])
            rows.append(dict(artist=artist,title=title,releaseDate=date,url=url2,source='Apple / iTunes',artwork=images[-1]['label'] if images else '',rank=rank,country=country))
        return genre,country,rows,None
    except Exception as e: return genre,country,[],str(e)
def match(row,articles):
    artist=norm(row['artist']);title=norm(re.sub(r'\s+-\s+(EP|Single)$','',row['title'],flags=re.I))
    if not artist or not title: return []
    out=[]
    for a in articles:
        if a.get('sourceId')!='inverted-audio.com': continue
        if not a.get('url','').startswith('https://inverted-audio.com/'): continue
        if not a.get('published'): continue
        signal=' '+norm(a.get('title',''))+' '
        if artist!=title and ' '+artist+' ' in signal and ' '+title+' ' in signal:
            out.append({k:a.get(k) for k in ('title','url','source','published','kind')})
    return out
def main():
    with ThreadPoolExecutor(max_workers=12) as pool:
        results=list(pool.map(fetch,[(g,i,c) for g,i in GENRES.items() for c in COUNTRIES]))
    articles=json.loads(Path('editorial/articles.json').read_text())['articles']
    ranked={};audit={}
    for g in GENRES:
        rows={};success=0
        for genre,country,items,error in results:
            if genre!=g: continue
            if error: continue
            success+=1
            for x in items:
                key=(norm(x['artist']),norm(x['title']))
                row=rows.setdefault(key,{**x,'signals':{}})
                row['signals'][country]=max(row['signals'].get(country,0),101-x['rank'])
        if not success: raise RuntimeError('No successful charts for '+g)
        for row in rows.values():
            row['score']=sum(row['signals'].values())
            row['articles']=match(row,articles)
        ranked[g]=sorted(rows.values(),key=lambda r:(-r['score'],r['artist'],r['title']))[:5]
        audit[g]={'successfulCharts':success,'eligible':len(rows),'selected':len(ranked[g]),'matched':sum(bool(r['articles']) for r in ranked[g])}
    output=dict(updated=dt.datetime.now(dt.timezone.utc).isoformat(),releaseDate=str(end),windowStart=str(start),genres=ranked,audit=audit)
    Path('underground.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(audit,ensure_ascii=False))
if __name__=='__main__': main()
