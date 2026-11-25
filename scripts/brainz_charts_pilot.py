import json,time,urllib.request,urllib.parse,urllib.error,datetime
from pathlib import Path
BASE="https://api.listenbrainz.org/1/stats/sitewide/"
MB="https://musicbrainz.org/ws/2/"
tags={"UK Garage":["uk garage","speed garage","2-step","2-step garage"],"Jungle":["jungle","ragga jungle"],"Drum & Bass":["drum and bass","drum & bass","dnb","liquid funk","atmospheric drum and bass"],"Breakbeat":["breakbeat","breaks","broken beat"],"Techno":["techno","dub techno","hard techno","minimal techno","hardgroove"],"Deep House":["deep house","minimal house"],"Ambient":["ambient","dark ambient","ambient electronic"],"Experimental":["experimental electronic","idm","experimental"]}
out={"charts":{},"errors":[],"licenses":{"listens":"CC0","tags":"MusicBrainz CC BY-NC-SA 3.0"}}
def call(url):
    for attempt in range(3):
        time.sleep(1.5)
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"SLIPP/0.3 (https://slipp.mathias-bratli.workers.dev/)","Accept":"application/json"}),timeout=20) as r:
                data=json.load(r)
                if r.headers.get("X-RateLimit-Remaining")=="0": time.sleep(int(r.headers.get("X-RateLimit-Reset-In","60"))+1)
                return data
        except urllib.error.HTTPError as e:
            if e.code not in (429,502,503,504) or attempt==2: raise
            delay=e.headers.get("Retry-After","")
            if delay and not delay.isdigit(): raise
            time.sleep(max(10*2**attempt,int(delay or 0)))
def save():
    Path("brainz-charts-results.json").write_text(json.dumps(out,ensure_ascii=False,indent=2))
for endpoint,key,entity in [("release-groups","release_groups","release-group"),("recordings","recordings","recording")]:
    report={"rows":0,"checked":0,"missing_id":0,"untagged":0,"genres":{g:[] for g in tags},"errors":[]}
    out["charts"][endpoint]=report
    seen=set()
    for offset in range(0,300,100):
        url=BASE+endpoint+"?"+urllib.parse.urlencode({"range":"month","count":100,"offset":offset})
        try:
            p=call(url)["payload"]
            period={k:p.get(k) for k in ("range","from_ts","to_ts","last_updated")}
            if "period" in report and period!=report["period"]: raise ValueError("Chart snapshot changed")
            report["period"]=period
            rows=p[key]
            if not rows: break
        except Exception as e:
            report["errors"].append(str(e));break
        for rank,row in enumerate(rows,offset+1):
            report["rows"]+=1
            mid=row.get(entity.replace("-","_")+"_mbid")
            if not mid: report["missing_id"]+=1;continue
            if mid in seen: continue
            seen.add(mid)
            source=MB+entity+"/"+mid+"?inc=tags+genres&fmt=json"
            try:
                m=call(source)
                report["checked"]+=1
                names={t["name"].casefold() for t in m.get("tags",[])+m.get("genres",[]) if t.get("count",0)>0}
                if not names: report["untagged"]+=1
                for genre,aliases in tags.items():
                    matches=sorted(names.intersection(aliases))
                    if matches:
                        report["genres"][genre].append({"rank":rank,"id":mid,"artist":row.get("artist_name"),"title":m.get("title"),"listens":row.get("listen_count"),"date":m.get("first-release-date"),"format":m.get("primary-type"),"matched_tags":matches,"metadata_url":"https://musicbrainz.org/"+entity+"/"+mid,"chart_url":url})
            except Exception as e:
                report["errors"].append({"rank":rank,"error":str(e)})
                if len(report["errors"])>=5: break
            save()
        if len(report["errors"])>=5 or len(rows)<100: break
    print(endpoint,json.dumps({"period":report.get("period"),"rows":report["rows"],"checked":report["checked"],"untagged":report["untagged"],"counts":{g:len(v) for g,v in report["genres"].items()},"top5":{g:v[:5] for g,v in report["genres"].items()},"errors":report["errors"]},ensure_ascii=False),flush=True)
    save()
if any(v["errors"] or not v["rows"] for v in out["charts"].values()): raise SystemExit("Incomplete chart pilot")
