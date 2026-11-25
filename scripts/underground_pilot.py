import json, datetime, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse
import sys

def eligible(s):
    return s.get("enabled") is True and s.get("permission_url","").startswith("https://") and s.get("feed","").startswith("https://") and {"title","url","published","source"}.issubset(s.get("allowed_fields",[]))

def parse(raw, source):
    root=ET.fromstring(raw)
    rows=[]
    for item in root.findall("./channel/item")[:30]:
        title=item.findtext("title")
        url=item.findtext("link")
        date=item.findtext("pubDate")
        if title and url and date and urlparse(url).scheme=="https" and urlparse(url).hostname in source.get("allowed_hosts",[]):
            rows.append(dict(title=title,url=url,published=date,source=source["name"]))
    return rows

if "--self-test" in sys.argv:
    assert not eligible({"enabled":True,"feed":"https://example.org/rss"})
    s={"name":"fixture","allowed_hosts":["example.org"]}
    assert len(parse(b"<rss><channel><item><title>Test</title><link>https://example.org/a</link><pubDate>test</pubDate></item></channel></rss>",s))==1
    print("Offline tests passed")
    sys.exit(0)

sources=json.loads(Path("underground/sources.json").read_text())["sources"]
rows=[]
for s in sources:
    if not eligible(s):
        print("Skipped:",s["name"])
        continue
    req=urllib.request.Request(s["feed"],headers={"User-Agent":"SLIPP RSS pilot"})
    with urllib.request.urlopen(req,timeout=20) as response:
        if response.geturl()!=s["feed"]:
            raise ValueError("Unexpected redirect; review source")
        rows.extend(parse(response.read(1000000),s))
Path("underground/pilot-results.json").write_text(json.dumps({"articles":rows},ensure_ascii=False,indent=2))
