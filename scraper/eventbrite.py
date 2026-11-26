"""Cyber events posted on Eventbrite, searched city by city across every state.
Fills in places where the scene doesn't use Meetup (Maryland, the Carolinas, the Plains...).
Strict on purpose: the event NAME has to say security/cyber/hacking, and "Cyber Monday" sales are dropped."""
import hashlib, json, re, time, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

UA = "Mozilla/5.0 (compatible; TheLineupBot/1.0; +https://thelineup.dev)"
STRICT = re.compile(r"\b(cyber\s?security|cyber|infosec|information security|security summit|security conference|hack(ers?|ing|athon)?|owasp|bsides|ctf|isc2|isaca|issa|soc analyst|pen ?test\w*|red team|blue team|zero trust|devsecops|osint)\b", re.I)
NOISE = re.compile(r"cyber ?monday|blockchain|crypto(currency)?|real estate|life ?hack|growth ?hack|travel ?hack|kids?|teen|summer camp", re.I)


def _slug(city):
    return re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")


def pull(cities_by_state, start, end, place, report, days=120):
    out, seen, failed = [], set(), []
    jobs = [(st, c, kw) for st, cs in cities_by_state.items() for c in cs[:2] for kw in ("cyber-security", "cybersecurity--events")]
    for st, city, kw in jobs:
        url = f"https://www.eventbrite.com/d/{st.lower()}--{_slug(city)}/{kw}/"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=25) as r:
                h = r.read().decode("utf-8", errors="replace")
            m = re.search(r"__SERVER_DATA__\s*=\s*", h)
            data, _ = json.JSONDecoder().raw_decode(h[m.end():])
            results = data.get("search_data", {}).get("events", {}).get("results", [])
        except Exception as exc:
            failed.append(f"{st}/{city}"); continue
        for e in results:
            name = (e.get("name") or "").strip()
            if not STRICT.search(name) or NOISE.search(name) or e.get("is_cancelled") or e.get("is_online_event"):
                continue
            ad = ((e.get("primary_venue") or {}).get("address") or {})
            if (ad.get("country") or "").upper() != "US" or not ad.get("city"):
                continue
            key = e.get("id") or e.get("url")
            if key in seen:
                continue
            tz = e.get("timezone") or "America/New_York"
            try:
                s = datetime.fromisoformat(f'{e["start_date"]}T{e.get("start_time") or "18:00"}').replace(tzinfo=ZoneInfo(tz))
                en = datetime.fromisoformat(f'{e.get("end_date") or e["start_date"]}T{e.get("end_time") or "20:00"}').replace(tzinfo=ZoneInfo(tz))
            except Exception:
                continue
            if not (start <= s.date() <= end) or s.date() > start + timedelta(days=days):
                continue
            seen.add(key)
            p = place(f'{ad.get("city")}, {ad.get("region")}')
            venue = (e.get("primary_venue") or {}).get("name") or ad.get("address_1") or p["city"]
            urg = (e.get("urgency_signals") or {}).get("messages") or []
            ev = {"id": "eb" + hashlib.sha1(str(key).encode()).hexdigest()[:10], "title": name,
                  "start": s.isoformat(), "end": en.isoformat(), "allDay": False, "tz": tz,
                  "venue": venue[:80], **p, "format": "In person", "cost": "Check listing",
                  "tags": ["cyber"] + (["ai"] if re.search(r"\bAI\b|artificial intelligence", name) else []),
                  "kind": "Conference" if en.date() > s.date() or re.search(r"summit|conference|con\b", name, re.I) else "Event",
                  "url": e.get("url"), "about": (e.get("summary") or "")[:220], "source": "Eventbrite",
                  "status": "listed", "cancelReason": None}
            if "salesEnded" in urg or "soldOut" in urg:
                ev["rsvp"] = {"going": 0, "max": 0, "waitlist": 0, "full": True}
            elif "goingFast" in urg or "fewTickets" in urg:
                ev["rsvp"] = {"going": 0, "max": 0, "waitlist": 0, "full": False, "near": True}
            out.append(ev)
        time.sleep(0.6)
    report.append({"source": "Eventbrite", "ok": len(failed) < len(jobs) / 2, "events": len(out),
                   **({"note": "search failed for " + ", ".join(failed)} if failed else {})})
    return out
