import json,time,urllib.request,urllib.error,collections
from pathlib import Path
genres={1044:"Breakbeat",1046:"Garage",1047:"Hardcore",1048:"House",1049:"Jungle/Drum'n'bass",1050:"Techno",1051:"Trance",1060:"IDM/Experimental",1941:"Dubstep",1942:"Bass",100014:"Dubstep",100015:"Bass"}
aliases={1060:{"idm/experimental","idm/experimenteel","idm/experimentell"},1049:{"jungle/drum'n'bass","jungle/drum & bass"}}
out={"method":"Current iTunes purchase chart snapshots; not 30-day streaming counts. Genre IDs are hypotheses to verify against returned labels.","results":[]}
for gid,label in genres.items():
    for country in ("gb","de","nl","us"):
        for kind in ("topsongs","topalbums"):
            url=f"https://itunes.apple.com/{country}/rss/{kind}/limit=100/genre={gid}/json"
            row={"requested_genre":label,"genre_id":gid,"country":country,"kind":kind,"source":url}
            try:
                time.sleep(1.5)
                with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"SLIPP/0.5 (https://slipp.mathias-bratli.workers.dev/)","Accept":"application/json"}),timeout=20) as response:
                    raw=response.read(2_000_001)
                    if len(raw)>2_000_000: raise ValueError("Response exceeds safety cap")
                    feed=json.loads(raw)["feed"]
                entries=feed.get("entry",[])
                if isinstance(entries,dict): entries=[entries]
                row["count"]=len(entries)
                row["feed_title"]=feed.get("title",{}).get("label")
                row["updated"]=feed.get("updated",{}).get("label")
                row["returned_genres"]=dict(collections.Counter(str(e.get("category",{}).get("attributes",{}).get("label","unknown")) for e in entries))
                row["returned_genre_ids"]=dict(collections.Counter(str(e.get("category",{}).get("attributes",{}).get("im:id","unknown")) for e in entries))
                allowed=aliases.get(gid,{label.casefold()})
                row["verified"]=bool(entries) and all(k.casefold() in allowed for k in row["returned_genres"]) and set(row["returned_genre_ids"])=={str(gid)}
                row["top5"]=[{"rank":i,"artist":e.get("im:artist",{}).get("label"),"title":e.get("im:name",{}).get("label"),"genre":e.get("category",{}).get("attributes",{}).get("label"),"id":e.get("id",{}).get("attributes",{}).get("im:id"),"url":e.get("id",{}).get("label")} for i,e in enumerate(entries[:5],1)]
            except Exception as e:
                row["error"]=str(e)
                if isinstance(e,urllib.error.HTTPError) and e.code==429:
                    out["results"].append(row)
                    Path("itunes-underground-report.json").write_text(json.dumps(out,ensure_ascii=False,indent=2))
                    raise SystemExit("Rate limited; stopping pilot")
            out["results"].append(row)
            print(json.dumps(row,ensure_ascii=False),flush=True)
            Path("itunes-underground-report.json").write_text(json.dumps(out,ensure_ascii=False,indent=2))
print("SUMMARY",json.dumps({g:{"working":sum(bool(r.get("verified")) for r in out["results"] if r["genre_id"]==g),"errors":sum("error" in r for r in out["results"] if r["genre_id"]==g)} for g in genres}),flush=True)
if not any(r.get("verified") for r in out["results"]): raise SystemExit("No usable feeds")
