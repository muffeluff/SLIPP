import collections, datetime as dt, hashlib, json, os, re, resource, subprocess, tarfile, tempfile, time, urllib.request, urllib.parse, uuid
from pathlib import Path
ROOT="https://data.metabrainz.org/pub/musicbrainz/listenbrainz/incremental/"
UA="SLIPP/0.4 (https://slipp.mathias-bratli.workers.dev/)"
START=time.monotonic()
out={"source":ROOT,"license":"ListenBrainz CC0; MusicBrainz tags CC BY-NC-SA 3.0","method":"one incremental submission archive; actual listening date filter; recording sample, not comprehensive chart","errors":[]}
def save():
    out["elapsed_seconds"]=round(time.monotonic()-START,2)
    out["peak_python_rss_kib"]=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    Path("brainz-dump-report.json").write_text(json.dumps(out,ensure_ascii=False,indent=2))
def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA})
    return urllib.request.urlopen(req,timeout=60)
def count_stream(lines,day,counts):
    metrics=collections.Counter()
    for raw in lines:
        metrics["rows"]+=1
        try:
            row=json.loads(raw)
            stamp=dt.datetime.fromtimestamp(row["listened_at"],dt.timezone.utc).date()
            if stamp!=day: continue
            metrics["target_day"]+=1
            md=row.get("track_metadata") or {}
            mapping=md.get("mbid_mapping") or row.get("mbid_mapping") or {}
            additional=md.get("additional_info") or {}
            mid=str(uuid.UUID(mapping.get("recording_mbid") or additional.get("recording_mbid") or row.get("recording_mbid") or ""))
            counts[mid]+=1
            metrics["mapped"]+=1
        except (ValueError,TypeError,KeyError,OverflowError,AttributeError):
            metrics["unmapped_or_invalid"]+=1
    return metrics
def selftest():
    day=dt.date(2026,11,24)
    ts=int(dt.datetime(2026,11,24,tzinfo=dt.timezone.utc).timestamp())
    mid="95acf775-12d3-44e2-a7db-06dc5dc34910"
    row={"listened_at":ts,"user_name":"fixture","track_metadata":{"additional_info":{"recording_mbid":mid}}}
    counts=collections.Counter()
    m=count_stream([json.dumps(row),json.dumps(dict(row,listened_at=ts-86400))],day,counts)
    assert counts[mid]==1 and m["target_day"]==1
    assert "fixture" not in json.dumps(counts)
selftest()
out["selftest"]="passed"
save()
try:
    endpoint="https://labs.api.listenbrainz.org/bulk-tag-lookup/json"
    mid="95acf775-12d3-44e2-a7db-06dc5dc34910"
    with get(endpoint+"?"+urllib.parse.urlencode({"recording_mbid":mid})) as response:
        out["independent_tag_probe"]={"endpoint":endpoint,"recording_mbid":mid,"response":json.load(response)}
except Exception as e:
    out["independent_tag_probe"]={"error":str(e)}
save()
try:
    with get(ROOT) as r: listing=r.read(4_000_000).decode()
    dirs=sorted(set(re.findall(r'listenbrainz-dump-\d+-\d{8}-\d{6}-incremental',listing)),key=lambda x:x.split("-")[3:5])
    if not dirs: raise ValueError("No incremental directories")
    out["archive_candidates"]=[]
    for directory in reversed(dirs[-7:]):
        dumpday=dt.datetime.strptime(directory.split("-")[3],"%Y%m%d").date()
        day=dumpday-dt.timedelta(days=1)
        url=ROOT+directory+"/"
        with get(url) as r: listing=r.read(4_000_000).decode()
        names=sorted(set(re.findall(r'listenbrainz-listens-dump[\w.-]*\.tar\.zst',listing)))
        if len(names)!=1: continue
        source=url+names[0]
        with urllib.request.urlopen(urllib.request.Request(source,method="HEAD",headers={"User-Agent":UA}),timeout=60) as response:
            length=int(response.headers.get("Content-Length") or 0)
        out["archive_candidates"].append({"url":source,"bytes":length})
        save()
        if 10*1024**2 <= length <= 2*1024**3: break
        time.sleep(2)
    else: raise ValueError("No suitable archive in last seven directories")
    out.update({"archive":source,"target_day":str(day)})
    counts=collections.Counter()
    metrics=collections.Counter()
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/"listens.tar.zst"
        size=0
        digest=hashlib.sha256()
        with get(source) as response,path.open("wb") as f:
            while chunk:=response.read(1024*1024):
                size+=len(chunk)
                if size>2*1024**3: raise ValueError("2 GiB download safety cap")
                digest.update(chunk);f.write(chunk)
        out.update({"download_bytes":size,"sha256":digest.hexdigest()})
        save()
        with subprocess.Popen(["zstd","-dc",str(path)],stdout=subprocess.PIPE) as proc:
            with tarfile.open(fileobj=proc.stdout,mode="r|") as archive:
                for member in archive:
                    if member.isfile():
                        suffix=Path(member.name).suffix.lower()
                        structure=out.setdefault("archive_structure",{})
                        info=structure.setdefault(suffix or "(none)",{"files":0,"bytes":0})
                        info["files"]+=1
                        info["bytes"]+=member.size
                        if suffix in (".listens",".jsonl",".ndjson",".json") or re.search(r"\.listens\.",member.name):
                            metrics.update(count_stream(archive.extractfile(member),day,counts))
            if proc.wait()!=0: raise RuntimeError("Decompression failed")
    out["counts"]=dict(metrics)
    out["distinct_recordings"]=len(counts)
    out["top_recordings"]=[{"recording_mbid":mid,"listens":n,"source":"https://musicbrainz.org/recording/"+mid} for mid,n in counts.most_common(100)]
    save()
    if not counts: raise ValueError("No explicit recording MBIDs in selected listening day")
    # Probe the documented labs endpoint without assuming that its name guarantees batch input.
    mid=counts.most_common(1)[0][0]
    time.sleep(2)
    endpoint="https://labs.api.listenbrainz.org/bulk-tag-lookup/json"
    with get(endpoint+"?"+urllib.parse.urlencode({"recording_mbid":mid})) as response:
        out["tag_probe"]={"endpoint":endpoint,"recording_mbid":mid,"response":json.load(response)}
    save()
except Exception as e:
    out["errors"].append(str(e))
    save()
    raise SystemExit("Pilot incomplete; inspect report")
