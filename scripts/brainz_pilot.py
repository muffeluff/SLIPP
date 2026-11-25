import datetime as dt, json, time, urllib.request, urllib.parse
from pathlib import Path
UA="SLIPP/0.1 (https://slipp.mathias-bratli.workers.dev/)"
def call(url, payload=None):
    time.sleep(1.2)
    req=urllib.request.Request(url,data=None if payload is None else json.dumps(payload).encode(),headers={"User-Agent":UA,"Accept":"application/json","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=25) as r:
        result=json.load(r)
        if r.headers.get("X-RateLimit-Remaining")=="0":
            time.sleep(int(r.headers.get("X-RateLimit-Reset-In","60"))+1)
        return result
today=dt.datetime.now(dt.timezone.utc).date()
start=today-dt.timedelta(days=6)
out={"start":str(start),"end":str(today),"tag_license":"CC BY-NC-SA 3.0; MusicBrainz","listen_license":"CC0; ListenBrainz","genres":{}}
for genre in ["uk garage","jungle","drum and bass","breakbeat","techno","deep house","ambient","experimental"]:
    q=f'tag:"{genre}" AND firstreleasedate:[{start} TO {today}]'
    try:
        data=call("https://musicbrainz.org/ws/2/release-group/?"+urllib.parse.urlencode({"query":q,"fmt":"json","limit":20}))
        rows=[]
        for x in data.get("release-groups",[]):
            date=x.get("first-release-date","")
            if len(date)!=10 or not str(start)<=date<=str(today): continue
            rows.append({"id":x["id"],"title":x["title"],"artist":"".join(a.get("name","")+a.get("joinphrase","") for a in x.get("artist-credit",[])),"date":date,"format":x.get("primary-type"),"url":"https://musicbrainz.org/release-group/"+x["id"]})
        if rows:
            stats=call("https://api.listenbrainz.org/1/popularity/release-group",{"release_group_mbids":[x["id"] for x in rows]})
            byid={x["release_group_mbid"]:x for x in stats}
            for x in rows:
                s=byid.get(x["id"],{})
                x["listeners"]=s.get("total_user_count")
                x["listens"]=s.get("total_listen_count")
        out["genres"][genre]={"catalog_count":data.get("count"),"rows":rows}
    except Exception as e:
        out["genres"][genre]={"error":str(e)}
        break
Path("brainz-pilot-results.json").write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out,ensure_ascii=False))
