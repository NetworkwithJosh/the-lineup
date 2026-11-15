#!/usr/bin/env python3
"""The Lineup scraper.

Pulls cybersecurity and AI events from public calendar feeds (Meetup groups,
Luma calendars, plain ICS URLs), expands standing meetups from rules, merges
hand-checked one-off events, and writes:

  site/data/events.json   what the website reads
  site/lineup.ics         a calendar feed people can subscribe to

Standard library only, so it runs anywhere Python 3.10+ runs.
Usage:  python scraper/scrape.py [--days 150] [--offline]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "scraper"
OUT_JSON = ROOT / "site" / "data" / "events.json"
OUT_ICS = ROOT / "site" / "lineup.ics"
HOME_TZ = ZoneInfo("America/New_York")
UA = "TheLineupBot/1.0 (+https://github.com/NetworkwithJosh/the-lineup; reads public calendar feeds)"
WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

CYBER_WORDS = re.compile(r"\b(cyber|security|infosec|hack|ctf|owasp|isaca|isc2|issa|grc|soc|threat|pentest|red team|blue team|privacy|zero trust|appsec|devsecops|malware|defcon|bsides)\b", re.I)
AI_WORDS = re.compile(r"\b(ai|a\.i\.|llm|agent|agents|agentic|machine learning|ml|genai|claude|gpt|openai|anthropic|copilot|rag|mcp)\b", re.I)
ONLINE_WORDS = re.compile(r"\b(online|virtual|zoom|webinar|livestream|google meet|teams)\b", re.I)
LOCAL_WORDS = re.compile(r"\b(new york|nyc|manhattan|brooklyn|queens|bronx|jersey|nj|newark|hoboken|princeton|philadelphia|philly|pa|stamford|ct|connecticut|long island)\b", re.I)


# ---------------------------------------------------------------- fetching
def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/calendar, text/html, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------- ICS parsing
def unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def parse_dt(value: str, params: dict) -> tuple[datetime, bool]:
    """Return (aware datetime in HOME_TZ, all_day)."""
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value[:8], "%Y%m%d").date()
        return datetime.combine(d, time(0, 0), HOME_TZ), True
    if value.endswith("Z"):
        dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    else:
        tz = HOME_TZ
        if "TZID" in params:
            try:
                tz = ZoneInfo(params["TZID"].strip('"'))
            except Exception:
                tz = HOME_TZ
        dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=tz)
    return dt.astimezone(HOME_TZ), False


def parse_ics(text: str) -> list[dict]:
    events, cur = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            parts = head.split(";")
            name = parts[0].upper()
            params = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
            cur[name] = (value, params)
    out = []
    for e in events:
        if "DTSTART" not in e or "SUMMARY" not in e:
            continue
        if e.get("STATUS", ("",))[0].upper() == "CANCELLED":
            continue
        start, all_day = parse_dt(*e["DTSTART"])
        end = parse_dt(*e["DTEND"])[0] if "DTEND" in e else start + timedelta(hours=2)
        if all_day and "DTEND" in e:
            end = end - timedelta(days=1)  # ICS all-day DTEND is exclusive
        out.append({
            "title": unescape(e["SUMMARY"][0]),
            "start": start, "end": end, "allDay": all_day,
            "location": unescape(e.get("LOCATION", ("",))[0]),
            "url": unescape(e.get("URL", ("",))[0]),
            "description": unescape(e.get("DESCRIPTION", ("",))[0])[:600],
        })
    return out


# ---------------------------------------------------------------- shaping
def classify_region(location: str, default: str) -> str:
    if ONLINE_WORDS.search(location or ""):
        return "online"
    if LOCAL_WORDS.search(location or ""):
        return "local"
    return default


def tags_for(text: str, base: list[str]) -> list[str]:
    tags = set(base)
    if CYBER_WORDS.search(text):
        tags.add("cyber")
    if AI_WORDS.search(text):
        tags.add("ai")
    return sorted(tags)


def split_location(loc: str) -> tuple[str, str]:
    loc = re.sub(r"\s+", " ", loc or "").strip()
    if not loc:
        return "Location on listing", ""
    parts = [p.strip() for p in loc.split(",")]
    if len(parts) >= 3:
        return ", ".join(parts[:2]), ", ".join(parts[2:4])
    return loc, ""


def guess_cost(text: str) -> str:
    if re.search(r"\bfree\b", text, re.I):
        return "Free"
    m = re.search(r"\$\s?\d[\d,]*(\.\d\d)?", text)
    return m.group(0).replace(" ", "") if m else "Check listing"


def make_id(title: str, start: datetime) -> str:
    key = re.sub(r"[^a-z0-9]+", "", title.lower())[:40] + start.strftime("%Y%m%d")
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def iso(dt: datetime, all_day: bool) -> str:
    return dt.date().isoformat() if all_day else dt.isoformat(timespec="minutes")


def shape_feed_event(e: dict, src: dict, source_name: str) -> dict | None:
    text = f"{e['title']} {e['description']} {e['location']}"
    region = classify_region(e["location"], src.get("region", "local"))
    if src.get("only_near") and region != "online":
        if not any(w in e["location"].lower() for w in src["only_near"]):
            return None
    tags = tags_for(text, src.get("tags", []))
    if not tags:
        return None
    venue, city = split_location(e["location"])
    if region == "online":
        venue, city = "Online", "Online"
    return {
        "id": make_id(e["title"], e["start"]),
        "title": e["title"],
        "start": iso(e["start"], e["allDay"]),
        "end": iso(e["end"], e["allDay"]),
        "allDay": e["allDay"],
        "tz": "America/New_York",
        "venue": venue, "city": city, "region": region,
        "format": "Online" if region == "online" else "In person",
        "cost": guess_cost(text),
        "tags": tags,
        "kind": "Meetup",
        "url": e["url"] or src.get("page", ""),
        "about": re.sub(r"\s+", " ", e["description"])[:220],
        "source": source_name,
        "status": "listed",
    }


def nth_weekday(year: int, month: int, weekday: int, nth: int) -> date | None:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    d += timedelta(weeks=nth - 1)
    return d if d.month == month else None


def expand_rules(rules: list[dict], start: date, end: date) -> list[dict]:
    out = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        for r in rules:
            d = nth_weekday(y, m, WEEKDAYS[r["weekday"]], r["nth"])
            if not d or d < start or d > end:
                continue
            hs, ms = map(int, r["start"].split(":"))
            he, me = map(int, r["end"].split(":"))
            s = datetime.combine(d, time(hs, ms), HOME_TZ)
            e = datetime.combine(d, time(he, me), HOME_TZ)
            out.append({
                "id": make_id(r["title"], s), "title": r["title"],
                "start": iso(s, False), "end": iso(e, False), "allDay": False, "tz": "America/New_York",
                "venue": r["venue"], "city": r["city"], "region": r["region"], "format": r["format"],
                "cost": r["cost"], "tags": r["tags"], "kind": r["kind"], "url": r["url"], "about": r["about"],
                "source": "Standing meetup", "status": "recurring",
            })
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def load_curated(start: date, end: date) -> list[dict]:
    data = json.loads((CFG / "curated.json").read_text())
    out = []
    for c in data["events"]:
        all_day = len(c["start"]) == 10
        tz = ZoneInfo(c.get("tz", "America/New_York"))
        if all_day:
            s_date, e_date = date.fromisoformat(c["start"]), date.fromisoformat(c["end"])
        else:
            s_dt = datetime.fromisoformat(c["start"]).replace(tzinfo=tz)
            e_dt = datetime.fromisoformat(c["end"]).replace(tzinfo=tz)
            s_date, e_date = s_dt.date(), e_dt.date()
        if e_date < start or s_date > end:
            continue
        ev = {k: c[k] for k in ("title", "venue", "city", "region", "format", "cost", "tags", "kind", "url", "about")}
        ev.update({
            "start": c["start"] if all_day else s_dt.isoformat(timespec="minutes"),
            "end": c["end"] if all_day else e_dt.isoformat(timespec="minutes"),
            "allDay": all_day, "tz": c.get("tz", "America/New_York"),
            "source": "Checked by hand", "status": c.get("status", "confirmed"),
        })
        ev["id"] = make_id(c["title"], datetime.combine(s_date, time(0), HOME_TZ))
        out.append(ev)
    return out


# ---------------------------------------------------------------- sources
def pull_feeds(sources: dict, start: date, end: date, report: list) -> list[dict]:
    out = []
    jobs = []
    for g in sources.get("meetup_groups", []):
        jobs.append((g, f"https://www.meetup.com/{g['slug']}/events/ical/", g["name"], f"https://www.meetup.com/{g['slug']}/events/"))
    for c in sources.get("luma_calendars", []):
        jobs.append((c, None, c["name"], f"https://luma.com/{c['slug']}"))
    for u in sources.get("ics_urls", []):
        jobs.append((u, u["url"], u["name"], u.get("page", u["url"])))
    for src, url, name, page in jobs:
        src = {**src, "page": page}
        try:
            if url is None:  # Luma: find the calendar id on its public page, then use its ICS feed
                html = fetch(page)
                m = re.search(r"\bcal-[A-Za-z0-9]{8,}\b", html)
                if not m:
                    raise ValueError("calendar id not found on page")
                url = f"https://api.lu.ma/ics/get?entity=calendar&id={m.group(0)}"
            evs = parse_ics(fetch(url))
            kept = 0
            for e in evs:
                if e["end"].date() < start or e["start"].date() > end:
                    continue
                shaped = shape_feed_event(e, src, name)
                if shaped:
                    out.append(shaped)
                    kept += 1
            report.append({"source": name, "ok": True, "events": kept})
        except Exception as exc:  # one dead feed never breaks the run
            report.append({"source": name, "ok": False, "error": str(exc)[:120]})
    return out


# ---------------------------------------------------------------- output
def dedupe(events: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    rank = {"confirmed": 3, "listed": 2, "verify": 1, "recurring": 0}
    for e in events:
        key = re.sub(r"[^a-z0-9]+", "", e["title"].lower())[:28] + e["start"][:10]
        if key not in seen or rank.get(e["status"], 0) > rank.get(seen[key]["status"], 0):
            seen[key] = e
    return sorted(seen.values(), key=lambda e: (e["start"][:10], e["start"]))


def ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def write_ics(events: list[dict], stamp: datetime) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//The Lineup//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:The Lineup: cyber + AI meetups", "X-WR-TIMEZONE:America/New_York",
             "REFRESH-INTERVAL;VALUE=DURATION:P1D"]
    for e in events:
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@the-lineup", f"DTSTAMP:{stamp.strftime('%Y%m%dT%H%M%SZ')}"]
        if e["allDay"]:
            s = date.fromisoformat(e["start"]); en = date.fromisoformat(e["end"]) + timedelta(days=1)
            lines += [f"DTSTART;VALUE=DATE:{s:%Y%m%d}", f"DTEND;VALUE=DATE:{en:%Y%m%d}"]
        else:
            s = datetime.fromisoformat(e["start"]).astimezone(timezone.utc)
            en = datetime.fromisoformat(e["end"]).astimezone(timezone.utc)
            lines += [f"DTSTART:{s:%Y%m%dT%H%M%SZ}", f"DTEND:{en:%Y%m%dT%H%M%SZ}"]
        loc = ", ".join(x for x in (e["venue"], e["city"]) if x and x != "Online") or "Online"
        lines += [f"SUMMARY:{ics_escape(e['title'])}", f"LOCATION:{ics_escape(loc)}",
                  f"DESCRIPTION:{ics_escape((e['about'] + ' ' + e['url']).strip())}"]
        if e["url"]:
            lines.append(f"URL:{e['url']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=150, help="how far ahead to look")
    ap.add_argument("--offline", action="store_true", help="skip network feeds (curated + standing only)")
    ap.add_argument("--fixture", help="parse this local .ics file as an extra feed (testing)")
    args = ap.parse_args()

    now = datetime.now(HOME_TZ)
    start, end = now.date(), now.date() + timedelta(days=args.days)
    sources = json.loads((CFG / "sources.json").read_text())
    rules = json.loads((CFG / "recurring.json").read_text())["rules"]
    report: list = []

    events = load_curated(start, end) + expand_rules(rules, start, end)
    if args.fixture:
        for e in parse_ics(Path(args.fixture).read_text()):
            shaped = shape_feed_event(e, {"tags": [], "region": "local", "page": ""}, "Fixture feed")
            if shaped and e["end"].date() >= start:
                events.append(shaped)
        report.append({"source": "Fixture feed", "ok": True})
    if not args.offline:
        events += pull_feeds(sources, start, end, report)

    events = dedupe(events)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generatedAt": now.isoformat(timespec="minutes"), "windowDays": args.days,
               "count": len(events), "sources": report, "events": events}
    OUT_JSON.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    OUT_ICS.write_text(write_ics(events, datetime.now(timezone.utc)))
    ok = sum(1 for r in report if r.get("ok"))
    print(f"{len(events)} events written. Feeds ok: {ok}/{len(report)}")
    for r in report:
        if not r.get("ok"):
            print(f"  feed failed: {r['source']}: {r['error']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
