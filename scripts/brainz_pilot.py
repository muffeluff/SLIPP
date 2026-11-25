import datetime as dt, json, time, urllib.request, urllib.parse, urllib.error
from pathlib import Path
UA="SLIPP/0.2 (https://slipp.mathias-bratli.workers.dev/)"
def call(url,payload=None):
    for attempt in range(3):
        time.sleep(1.5)
        req=urllib.request.Request(url,data=None if payload is None else json.dumps(payload).encode(),headers={"User-Agent":UA,"Accept":"application/json","Content-Type":"application/json"})
        try:
            with urllib.request.urlopen(req,timeout=20) as r:
                data=json.load(r)
                if r.headers.get("X-RateLimit-Remaining")=="0":
                    time.sleep(int(r.headers.get("X-RateLimit-Reset-In","60"))+1)
                return data
        except urllib.error.HTTPError as e:
            if e.code not in (429,502,503,504) or attempt==2: raise
            delay=e.headers.get("Retry-After","")
            if delay and not delay.isdigit(): raise
            time.sleep(max(5*2**attempt,int(delay or 0)))
today=dt.datetime.now(dt.timezone.utc).date()
start=today-dt.timedelta(days=29)
tags={"uk garage":["uk garage","speed garage","2-step garage"],"jungle":["jungle","ragga jungle"],"drum and bass":["drum and bass","drum & bass","dnb"],"breakbeat":["breakbeat","breaks","broken beat"],"techno":["techno","hardgroove","dub techno"],"deep house":["deep house","minimal house"],"ambient":["ambient","dark ambient"],"experimental":["experimental electronic","idm","experimental"]}
out={"end":str(today),"tag_license":"CC BY-NC-SA 3.0; MusicBrainz","listen_license":"CC0; ListenBrainz","genres":{}}
errors=[]
for genre,aliases in tags.items():
    g={"rows":[],"errors":[],"windows":{}}
    out["genres"][genre]=g
    q="("+" OR ".join('tag:"'+a+'"' for a in aliases)+f") AND firstreleasedate:[{start} TO {today}]"
    try:
        data=call("https://musicbrainz.org/ws/2/release-group/?"+urllib.parse.urlencode({"query":q,"fmt":"json","limit":100}))
        g["catalog_count"]=data.get("count")
        for x in data.get("release-groups",[]):
            date=x.get("first-release-date","")
            if len(date)!=10 or not str(start)<=date<=str(today): continue
            g["rows"].append({"id":x["id"],"title":x["title"],"artist":"".join(a.get("name","")+a.get("joinphrase","") for a in x.get("artist-credit",[])),"date":date,"format":x.get("primary-type"),"tags":x.get("tags",[]),"url":"https://musicbrainz.org/release-group/"+x["id"]})
    except Exception as e:
        g["errors"].append("catalog: "+str(e))
    rows=g["rows"]
    for offset in range(0,len(rows),25):
        batch=rows[offset:offset+25]
        try:
            stats=call("https://api.listenbrainz.org/1/popularity/release-group",{"release_group_mbids":[x["id"] for x in batch]})
            if not isinstance(stats,list): raise ValueError("Unexpected response shape: "+str(stats)[:500])
            byid={x["release_group_mbid"]:x for x in stats}
            g.setdefault("stats_sample",stats[:2])
            for x in batch:
                s=byid.get(x["id"],{})
                x["listeners"]=s.get("total_user_count")
                x["listens"]=s.get("total_listen_count")
                x["popularity_raw"]=s
        except Exception as e:
            g["errors"].append("release popularity: "+str(e))
    # Bounded recording-level probe: one release group per genre, up to five recordings.
    if rows:
        try:
            rg=rows[0]["id"]
            releases=call("https://musicbrainz.org/ws/2/release?"+urllib.parse.urlencode({"release-group":rg,"inc":"recordings","fmt":"json","limit":1}))
            ids=list(dict.fromkeys(t["recording"]["id"] for rel in releases.get("releases",[]) for m in rel.get("media",[]) for t in m.get("tracks",[]) if t.get("recording",{}).get("id")))[:5]
            if ids:
                g["recording_probe"]={"ids":ids,"raw":call("https://api.listenbrainz.org/1/popularity/recording",{"recording_mbids":ids})}
        except Exception as e:
            g["errors"].append("recording probe: "+str(e))
    for days in (7,14,30):
        subset=[x for x in rows if x["date"]>=str(today-dt.timedelta(days=days-1))]
        g["windows"][str(days)]={"rows":len(subset),"with_stats":sum(x.get("listeners") is not None or x.get("listens") is not None for x in subset)}
    errors.extend(g["errors"])
    print(genre,json.dumps({"windows":g["windows"],"errors":g["errors"],"sample":rows[:2],"recording_probe":g.get("recording_probe")},ensure_ascii=False),flush=True)
out["complete"]=not errors
Path("brainz-pilot-results.json").write_text(json.dumps(out,ensure_ascii=False,indent=2))
if errors: raise SystemExit("Partial test: "+str(len(errors))+" errors; inspect artifact")
