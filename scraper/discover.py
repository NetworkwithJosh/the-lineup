"""Find new cyber meetup groups we aren't tracking yet, using Meetup's own city search.

For every US state (busiest cities first) it searches "cybersecurity", "hacking" and "information security",
keeps groups whose upcoming events are clearly cyber, and saves them to scraper/discovered.json.
The scraper then follows those groups like any other (only keeping events that look cyber/AI/IT).
Runs weekly. Hand-curated groups in sources.json always win; to block a bad find, add its slug to "blocked"."""
import json, re, sys, time, urllib.parse, urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

UA = "Mozilla/5.0 (compatible; TheLineupBot/1.0; +https://thelineup.dev)"
# stricter than the site's filter on purpose: a new group has to *be* a security group, not mention it once
STRICT = re.compile(r"\b(cyber\w*|infosec|info ?sec|security|hackers?|hacking|owasp|def ?con|dc\d{3}|bsides|ctf|pen ?test\w*|red team|blue team|isc2|isaca|issa|osint|malware|appsec|devsecops|2600)\b", re.I)
# groups that look cyber but aren't useful here (online reposts, AI-safety reading groups, generic data clubs)
NOISE = re.compile(r"control-systems|cyber-security-for-control|ai-safety-awareness|analytics\.?club|^ac-|^lfdt-|code-for-|real-estate|humanist|toastmaster", re.I)
KEYWORDS = ["cybersecurity", "hacking", "information security"]
CITIES = {
 "AL":["Huntsville","Birmingham"],"AK":["Anchorage"],"AZ":["Phoenix","Tucson"],"AR":["Little Rock","Fayetteville"],
 "CA":["San Francisco","Los Angeles","San Diego","Sacramento"],"CO":["Denver","Colorado Springs"],"CT":["Hartford","New Haven"],
 "DE":["Wilmington","Dover"],"DC":["Washington"],"FL":["Miami","Tampa","Orlando","Jacksonville"],"GA":["Atlanta","Augusta"],
 "HI":["Honolulu"],"ID":["Boise"],"IL":["Chicago"],"IN":["Indianapolis"],"IA":["Des Moines"],"KS":["Wichita","Kansas City"],
 "KY":["Louisville","Lexington"],"LA":["New Orleans","Baton Rouge"],"ME":["Portland"],"MD":["Baltimore","Columbia"],
 "MA":["Boston"],"MI":["Detroit","Grand Rapids"],"MN":["Minneapolis"],"MS":["Jackson"],"MO":["St. Louis","Kansas City"],
 "MT":["Billings","Missoula"],"NE":["Omaha","Lincoln"],"NV":["Las Vegas","Reno"],"NH":["Manchester"],"NJ":["Newark","Princeton"],
 "NM":["Albuquerque"],"NY":["New York","Albany","Rochester"],"NC":["Charlotte","Raleigh"],"ND":["Fargo"],"OH":["Columbus","Cleveland","Cincinnati"],
 "OK":["Oklahoma City","Tulsa"],"OR":["Portland"],"PA":["Philadelphia","Pittsburgh"],"RI":["Providence"],"SC":["Columbia","Charleston"],
 "SD":["Sioux Falls"],"TN":["Nashville","Knoxville"],"TX":["Austin","Dallas","Houston","San Antonio"],"UT":["Salt Lake City"],
 "VT":["Burlington"],"VA":["Arlington","Richmond","Virginia Beach"],"WA":["Seattle"],"WV":["Charleston"],"WI":["Milwaukee","Madison"],"WY":["Cheyenne"]}


def search(st, city, kw):
    loc = f"us--{st.lower()}--{city}"
    url = "https://www.meetup.com/find/?" + urllib.parse.urlencode({"location": loc, "source": "EVENTS", "keywords": kw, "distance": "fiftyMiles"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=25) as r:
        h = r.read().decode("utf-8", errors="replace")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    if not m:
        return []
    ap = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__") or {}
    out = []
    for k, v in ap.items():
        if not k.startswith("Event:"):
            continue
        g = ap.get((v.get("group") or {}).get("__ref", ""), {})
        ven = v.get("venue") or {}
        if g.get("urlname") and v.get("eventType") == "PHYSICAL" and (ven.get("country") or "").lower() == "us" and ven.get("city") and ven.get("state"):
            out.append({"slug": g["urlname"], "name": g.get("name") or g["urlname"], "title": v.get("title") or "",
                        "home": f"{ven['city'].title()}, {ven['state'].upper()}"})
    return out


def main():
    src = json.loads((HERE / "sources.json").read_text())
    path = HERE / "discovered.json"
    disc = json.loads(path.read_text()) if path.exists() else {"blocked": [], "groups": []}
    known = {g["slug"].lower() for g in src["meetup_groups"]} | {g["slug"].lower() for g in disc["groups"]} | {b.lower() for b in disc["blocked"]}
    found = {}
    for st, cities in CITIES.items():
        for city in cities:
            for kw in KEYWORDS:
                try:
                    hits = search(st, city, kw)
                except Exception as exc:
                    print("search failed", st, city, kw, exc, file=sys.stderr); continue
                for h in hits:
                    s = h["slug"].lower()
                    if s in known:
                        continue
                    if NOISE.search(h["slug"]) or NOISE.search(h["name"]):
                        continue
                    # the group's name has to say security, or one of its in-person events does
                    if STRICT.search(h["name"]) or STRICT.search(h["title"]):
                        f = found.setdefault(s, {"slug": h["slug"], "name": h["name"], "home": h["home"], "hits": 0})
                        f["hits"] += 1
                time.sleep(0.6)
    added = []
    for f in found.values():
        g = {"slug": f["slug"], "name": f["name"][:80], "tags": ["cyber"], "home": f["home"], "require_keywords": True,
             "found": date.today().isoformat()}
        disc["groups"].append(g); added.append(g)
    disc["groups"].sort(key=lambda g: g["slug"].lower())
    path.write_text(json.dumps(disc, indent=2, ensure_ascii=False) + "\n")
    print(f"discover: {len(added)} new groups")
    for g in added:
        print(" +", g["slug"], "|", g["name"], "|", g["home"])


if __name__ == "__main__":
    main()
