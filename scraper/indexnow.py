"""Tell Bing (and other IndexNow engines) about new or changed pages right after each refresh, instead of waiting for a crawl.
The key is public by design: it just proves we own thelineup.dev (the matching file sits at /88e0e47140cc19eada515d87230a852e.txt)."""
import json, sys, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path

KEY = "88e0e47140cc19eada515d87230a852e"
HOST = "thelineup.dev"

def main():
    root = Path(__file__).resolve().parent.parent / "site"
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [u.text for u in ET.parse(root / "sitemap.xml").getroot().findall("s:url/s:loc", ns)][:10000]
    body = json.dumps({"host": HOST, "key": KEY, "keyLocation": f"https://{HOST}/{KEY}.txt", "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"indexnow: sent {len(urls)} urls, status {r.status}")

if __name__ == "__main__":
    try: main()
    except Exception as exc: print("indexnow failed:", exc, file=sys.stderr)
