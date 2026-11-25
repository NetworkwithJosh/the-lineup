"""City coordinates for "Near me", cached in the repo so each city is looked up once, ever.

Uses OpenStreetMap's Nominatim, politely: one request a second, a real User-Agent, and a cap per run.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path(__file__).parent / "geocache.json"
UA = "TheLineup/1.0 (+https://thelineup.dev; community event listings)"
SKIP = {"", "Online", "Location on listing", "Unknown"}


def key(e: dict) -> str | None:
    if e.get("online") or e.get("city") in SKIP:
        return None
    return "|".join([e["city"], e.get("state") or "", e.get("country") if e.get("country") not in SKIP else ""])


def lookup(k: str) -> list | None:
    city, state, country = k.split("|")
    q = {"city": city, "format": "jsonv2", "limit": "1"}
    if state:
        q["state"] = state
    if country:
        q["country"] = country
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read())
    if not res:  # "city" can be a venue or neighbourhood; fall back to free text
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": ", ".join(x for x in (city, state, country) if x), "format": "jsonv2", "limit": "1"})
        time.sleep(1.1)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
            res = json.loads(r.read())
    return [round(float(res[0]["lat"]), 3), round(float(res[0]["lon"]), 3)] if res else None


def attach(events: list[dict], max_lookups: int = 80, offline: bool = False) -> int:
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    looked = 0
    for e in events:
        k = key(e)
        if not k:
            continue
        if k not in cache and not offline and looked < max_lookups:
            try:
                cache[k] = lookup(k)
            except Exception:
                pass  # network hiccup: try this city again next run
            looked += 1
            time.sleep(1.1)
        if cache.get(k):
            e["lat"], e["lng"] = cache[k]
    if looked:
        CACHE.write_text(json.dumps(dict(sorted(cache.items())), indent=0, ensure_ascii=False))
    return looked
