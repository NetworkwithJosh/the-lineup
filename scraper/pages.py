"""Static per-state pages and calendar feeds, rebuilt on every scrape.

site/us/index.html            every state with its event count
site/us/<state>/index.html    a plain, crawlable list for that state (what Google indexes)
site/feeds/<st>.ics           calendar feed with only that state's in-person events
"""
from __future__ import annotations

import html
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

BASE = "https://thelineup.dev"
TAG = {"cyber": "Cyber", "ai": "AI", "it": "IT"}

STYLE = """
:root{--bg:#0b0d10;--card:#12161b;--line:#232a32;--ink:#e9edf1;--soft:#9aa7b4;--dim:#7d8996;--acc:#ffb547}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 Geist,system-ui,sans-serif}
a{color:var(--ink)}a:hover{color:var(--acc)}
.wrap{max-width:860px;margin:0 auto;padding:28px 20px 64px}
.top{display:flex;align-items:center;gap:10px;font-weight:600;text-decoration:none;margin-bottom:28px}
.top i{width:12px;height:12px;border-radius:3px;background:var(--acc);display:inline-block}
h1{font-size:clamp(1.7rem,4vw,2.4rem);line-height:1.15;margin:0 0 10px;letter-spacing:-.02em}
.lede{color:var(--soft);margin:0 0 22px;max-width:62ch}
.cta{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 30px}
.btn{display:inline-flex;align-items:center;min-height:42px;padding:.55rem 1rem;border-radius:8px;border:1px solid var(--line);text-decoration:none;font-size:.9rem}
.btn--solid{background:var(--acc);color:#17120a;border-color:var(--acc);font-weight:600}
.btn--solid:hover{color:#17120a}
h2{font:500 .78rem/1 "Geist Mono",ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--dim);margin:30px 0 8px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.ev{display:grid;grid-template-columns:92px 1fr;gap:14px;padding:14px 0;border-bottom:1px solid var(--line)}
.when{font:500 .85rem/1.35 "Geist Mono",ui-monospace,monospace;color:var(--soft)}.when b{display:block;color:var(--ink);font-weight:500}
.ev h3{font-size:1rem;margin:0 0 4px;font-weight:600}.ev h3 a{text-decoration:none}
.meta{color:var(--soft);font-size:.88rem;margin:0}.tags{color:var(--dim);font:500 .72rem "Geist Mono",monospace;letter-spacing:.06em;text-transform:uppercase;margin-top:4px}
.states{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px;padding:0;list-style:none}
.states a{display:flex;justify-content:space-between;padding:12px 14px;border:1px solid var(--line);border-radius:8px;text-decoration:none;background:var(--card)}
.states span{color:var(--dim);font-family:"Geist Mono",monospace}
.foot{color:var(--dim);font-size:.85rem;margin-top:36px}
"""


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def page(title: str, desc: str, canonical: str, body: str, ld: str = "") -> str:
    e = html.escape
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}"><link rel="canonical" href="{canonical}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{canonical}">
<meta name="theme-color" content="#0b0d10">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%230b0d10'/><rect x='7' y='9' width='18' height='3' rx='1.5' fill='%23ffb547'/><rect x='7' y='15' width='12' height='3' rx='1.5' fill='%23e9edf1'/><rect x='7' y='21' width='15' height='3' rx='1.5' fill='%238b98a6'/></svg>">
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{STYLE}</style>{ld}</head>
<body><div class="wrap"><a class="top" href="/"><i></i>The Lineup</a>{body}
<p class="foot">The Lineup lists events other people organize and refreshes every day. Check the organizer's page before you go.</p></div></body></html>
"""


def when(e: dict) -> tuple[str, str]:
    if e["allDay"]:
        s, en = date.fromisoformat(e["start"]), date.fromisoformat(e["end"])
        day = f"{s:%a} {s:%b} {s.day}"
        return day, ("All day" if s == en else f"to {en:%b} {en.day}")
    d = datetime.fromisoformat(e["start"])
    return f"{d:%a} {d:%b} {d.day}", d.strftime("%I:%M %p").lstrip("0")


def event_ld(e: dict) -> dict:
    return {"@type": "Event", "name": e["title"], "startDate": e["start"], "endDate": e["end"],
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "eventStatus": "https://schema.org/EventScheduled", "url": e.get("url") or BASE,
            "location": {"@type": "Place", "name": e.get("venue") or e["city"],
                         "address": {"@type": "PostalAddress", "addressLocality": e["city"], "addressRegion": e["state"], "addressCountry": "US"}}}


def build(events: list[dict], state_names: dict, write_ics, now: datetime, site: Path) -> list[str]:
    """Write the state pages and feeds. Returns the page URLs for the sitemap."""
    import json
    live = [e for e in events if e["status"] != "cancelled" and not e.get("online") and e.get("country") == "United States" and e.get("state")]
    by_state: dict[str, list[dict]] = {}
    for e in live:
        by_state.setdefault(e["state"], []).append(e)

    for d in (site / "us", site / "feeds"):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    urls = [f"{BASE}/us/"]
    e = html.escape

    for st, evs in by_state.items():
        name = state_names.get(st, st)
        evs.sort(key=lambda x: (x["start"][:10], x["start"]))
        (site / "feeds" / f"{st.lower()}.ics").write_text(write_ics(evs, now))
        app = f"/?country=United%20States&state={st}"
        feed = f"{BASE}/feeds/{st.lower()}.ics"
        webcal = feed.replace("https:", "webcal:")
        rows, month = [], ""
        for x in evs:
            d = date.fromisoformat(x["start"][:10])
            m = f"{d:%B %Y}"
            if m != month:
                rows.append(f"<h2>{m}</h2>")
                month = m
            day, t = when(x)
            where = ", ".join(v for v in dict.fromkeys([x.get("venue") if x.get("venue") not in (x["city"], "Location on listing") else "", x["city"]]) if v and v != "Location on listing")
            title = f'<a href="{e(x["url"])}" rel="noopener">{e(x["title"])}</a>' if x.get("url") else e(x["title"])
            rows.append(f'<article class="ev"><div class="when"><b>{e(day)}</b>{e(t)}</div><div><h3>{title}</h3>'
                        f'<p class="meta">{e(where)}{" · " + e(x["cost"]) if x.get("cost") and x["cost"] != "Check listing" else ""}</p>'
                        f'<div class="tags">{" · ".join(TAG.get(t, t) for t in x["tags"])}</div></div></article>')
        cities = sorted({x["city"] for x in evs if x["city"] != "Location on listing"}, key=lambda c: -sum(1 for y in evs if y["city"] == c))[:6]
        title = f"Cybersecurity, AI and IT meetups in {name} | The Lineup"
        desc = (f"{len(evs)} upcoming cybersecurity, AI and IT meetups, chapter meetings and conferences in {name}"
                f"{' including ' + ', '.join(cities[:4]) if cities else ''}. Updated every day.")
        ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@graph": [event_ld(x) for x in evs[:40]]}) + "</script>"
        body = (f"<h1>Cyber, AI and IT meetups in {e(name)}</h1>"
                f'<p class="lede">{len(evs)} upcoming in-person events{(" in " + e(", ".join(cities))) if cities else ""}, pulled from Meetup groups, chapter calendars and conference lists. Updated {now:%b} {now.day}.</p>'
                f'<div class="cta"><a class="btn btn--solid" href="{app}">See what you can make after work</a>'
                f'<a class="btn" href="{webcal}">Subscribe to {e(name)} only</a>'
                f'<a class="btn" href="https://calendar.google.com/calendar/r?cid={quote(webcal, safe="")}" rel="noopener">Add to Google Calendar</a>'
                f'<a class="btn" href="/us/">All states</a></div>' + "".join(rows))
        p = site / "us" / slug(name)
        p.mkdir(parents=True, exist_ok=True)
        (p / "index.html").write_text(page(title, desc, f"{BASE}/us/{slug(name)}/", body, ld))
        urls.append(f"{BASE}/us/{slug(name)}/")

    items = "".join(f'<li><a href="/us/{slug(state_names.get(st, st))}/">{e(state_names.get(st, st))}<span>{len(v)}</span></a></li>'
                    for st, v in sorted(by_state.items(), key=lambda kv: state_names.get(kv[0], kv[0])))
    body = (f"<h1>Cyber, AI and IT meetups by state</h1>"
            f'<p class="lede">{len(live)} upcoming in-person events across {len(by_state)} states. Pick yours for the full list and a calendar feed with just your state.</p>'
            f'<ul class="states">{items}</ul>')
    (site / "us" / "index.html").write_text(page("Cybersecurity, AI and IT meetups by US state | The Lineup",
                                                 f"Upcoming cybersecurity, AI and IT meetups in {len(by_state)} US states, updated every day.",
                                                 f"{BASE}/us/", body))
    return urls
