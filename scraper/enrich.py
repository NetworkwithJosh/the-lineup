"""Look at each upcoming Meetup event's own page for what the calendar feed leaves out:
  - is it full / waitlist only, and how many people RSVP'd
  - is it actually online (Meetup says so even when the title doesn't)
Only checks events in the next few weeks, a few at a time, so we stay polite.
Results are cached on the event, so a failed fetch keeps the last known status."""
import json, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

UA = "Mozilla/5.0 (compatible; TheLineupBot/1.0; +https://thelineup.dev)"
DAYS, MAX_PAGES = 21, 160


def _start(e):
    s = e["start"]
    d = datetime.fromisoformat(s if len(s) > 10 else s + "T12:00:00")
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _status(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=20) as r:
        h = r.read().decode("utf-8", errors="replace")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    if not m:
        return None
    ap = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("__APOLLO_STATE__") or {}
    ev = next((v for k, v in ap.items() if k.startswith("Event:")), None)
    if not ev:
        return None
    count = lambda key: ((ev.get(key) or {}).get("totalCount") or 0) if isinstance(ev.get(key), dict) else 0
    yes = count('rsvps({"filter":{"rsvpStatus":["YES"]}})')
    wait = count('rsvps({"filter":{"rsvpStatus":["WAITLIST"]}})')
    cap = int(ev.get("maxTickets") or 0)
    return {"going": yes, "max": cap, "waitlist": wait,
            "full": bool((cap and yes >= cap) or wait > 0),
            "type": ev.get("eventType"), "status": ev.get("status")}


def _norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()[:40]


def luma(events, calendars):
    """Luma calendar pages list each upcoming event with sold-out / spots-left / waitlist info.
    One page per calendar, then we match entries to our events by title + day."""
    ours = {}
    for e in events:
        if e["status"] != "cancelled":
            ours.setdefault((e.get("source"), _norm(e["title"]), e["start"][:10]), []).append(e)
    hits = 0
    for c in calendars or []:
        try:
            req = urllib.request.Request(f"https://luma.com/{c['slug']}", headers={"User-Agent": UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=20) as r:
                h = r.read().decode("utf-8", errors="replace")
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
            data = json.loads(m.group(1))["props"]["pageProps"]["initialData"]["data"]
            entries = (data.get("upcoming") or {}).get("entries") or []
        except Exception:
            continue
        for en in entries:
            ev, ti = en.get("event") or {}, en.get("ticket_info") or {}
            day = (ev.get("start_at") or "")[:10]
            for k in [(c["name"], _norm(ev.get("name")), day)]:
                for e in ours.get(k, []):
                    left = ti.get("spots_remaining")
                    full = bool(ti.get("is_sold_out") or en.get("waitlist_active"))
                    e["rsvp"] = {"going": en.get("guest_count") or 0, "max": 0, "waitlist": 1 if en.get("waitlist_active") else 0,
                                 "full": full, "left": left, "near": bool(ti.get("is_near_capacity"))}
                    if ev.get("url") and ("luma.com/" + c["slug"]) in (e.get("url") or "") or not e.get("url"):
                        e["url"] = "https://luma.com/" + ev["url"]  # link straight to the event, not the calendar
                    hits += 1
        time.sleep(0.5)
    print(f"enrich: matched {hits} Luma events")


def attach(events, prev_events=None, now=None, calendars=None):
    now = now or datetime.now(timezone.utc)
    old = {e["id"]: e.get("rsvp") for e in (prev_events or []) if e.get("rsvp")}
    todo = [e for e in events if "meetup.com/" in (e.get("url") or "") and "/events/" in e["url"]
            and e["status"] != "cancelled" and now - timedelta(hours=6) <= _start(e) <= now + timedelta(days=DAYS)]
    todo = sorted(todo, key=_start)[:MAX_PAGES]
    for e in events:  # keep last known status until we refresh it
        if e["id"] in old and not e.get("rsvp"):
            e["rsvp"] = old[e["id"]]

    def one(e):
        time.sleep(0.4)
        try:
            return e, _status(e["url"])
        except Exception:
            return e, None

    got = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for e, st in pool.map(one, todo):
            if not st:
                continue
            got += 1
            e["rsvp"] = {k: st[k] for k in ("going", "max", "waitlist", "full")}
            if st["type"] == "ONLINE" and not e.get("online"):
                e.update({"online": True, "city": "Online", "country": "Online", "metro": "Online", "state": "",
                          "venue": "Online", "format": "Online"})
                e.pop("lat", None); e.pop("lng", None)
    print(f"enrich: checked {got} of {len(todo)} upcoming Meetup events")
    luma(events, calendars)
