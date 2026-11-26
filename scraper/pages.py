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
<meta property="og:type" content="website"><meta property="og:site_name" content="The Lineup"><meta property="og:image" content="{BASE}/og.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#0b0d10">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%230b0d10'/><rect x='7' y='9' width='18' height='3' rx='1.5' fill='%23ffb547'/><rect x='7' y='15' width='12' height='3' rx='1.5' fill='%23e9edf1'/><rect x='7' y='21' width='15' height='3' rx='1.5' fill='%238b98a6'/></svg>">
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{STYLE}</style>{ld}<script src="/a.js" defer></script></head>
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


COUNTRY_CODES = {"United States": "US", "Canada": "CA", "United Kingdom": "GB", "Australia": "AU", "Germany": "DE", "France": "FR",
                 "Netherlands": "NL", "India": "IN", "Singapore": "SG", "Ireland": "IE", "Spain": "ES", "Italy": "IT", "Brazil": "BR",
                 "Japan": "JP", "New Zealand": "NZ", "Belgium": "BE", "Sweden": "SE", "Switzerland": "CH", "Finland": "FI",
                 "Mexico": "MX", "Israel": "IL", "United Arab Emirates": "AE", "Poland": "PL", "Portugal": "PT", "Denmark": "DK"}


def event_ld(e: dict) -> dict:
    online = bool(e.get("online"))
    ld = {"@type": "Event", "name": e["title"], "startDate": e["start"], "endDate": e["end"],
          "eventAttendanceMode": "https://schema.org/" + ("OnlineEventAttendanceMode" if online else "OfflineEventAttendanceMode"),
          "eventStatus": "https://schema.org/" + ("EventCancelled" if e["status"] == "cancelled" else "EventScheduled"),
          "image": [f"{BASE}/og.png"], "url": e.get("url") or BASE,
          "organizer": {"@type": "Organization", "name": re.sub(r" \((?:CSNP|DEF CON.*?)\)$", "", e.get("source") or "The Lineup"), "url": e.get("url") or BASE}}
    if e.get("about"):
        ld["description"] = e["about"][:300]
    if online:
        ld["location"] = {"@type": "VirtualLocation", "url": e.get("url") or BASE}
    else:
        addr = {"@type": "PostalAddress", "addressLocality": e["city"] if e["city"] != "Location on listing" else ""}
        if e.get("state"):
            addr["addressRegion"] = e["state"]
        if e.get("country") in COUNTRY_CODES:
            addr["addressCountry"] = COUNTRY_CODES[e["country"]]
        venue = e.get("venue") if e.get("venue") not in (None, "", "Location on listing") else e["city"]
        ld["location"] = {"@type": "Place", "name": venue, "address": addr}
    cost = (e.get("cost") or "").lower()
    if cost.startswith("free"):
        ld["isAccessibleForFree"] = True
        ld["offers"] = {"@type": "Offer", "price": "0", "priceCurrency": "USD", "url": e.get("url") or BASE, "availability": "https://schema.org/InStock"}
    else:
        m = re.search(r"\$\s?(\d+(?:\.\d{2})?)", e.get("cost") or "")
        if m:
            ld["offers"] = {"@type": "Offer", "price": m.group(1), "priceCurrency": "USD", "url": e.get("url") or BASE, "availability": "https://schema.org/InStock"}
    return ld


def event_slug(e: dict) -> str:
    return (slug(e["title"])[:60].strip("-") or "event") + "-" + e["id"][:8]


def build_events(events: list[dict], state_names: dict, now: datetime, site: Path) -> list[str]:
    """One crawlable page per upcoming event, with Google's Event markup so it can show up in event search."""
    import json
    out = site / "event"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    esc = html.escape
    urls = []
    for x in events:
        if x["status"] == "cancelled":
            continue
        sl = event_slug(x)
        day, t = when(x)
        d0 = date.fromisoformat(x["start"][:10])
        place = "Online" if x.get("online") else ", ".join(v for v in dict.fromkeys([
            x.get("venue") if x.get("venue") not in (x["city"], "Location on listing") else "",
            x["city"] if x["city"] != "Location on listing" else "",
            state_names.get(x.get("state"), "") if x.get("state") else (x["country"] if x["country"] not in ("Unknown", "Online") else "")]) if v)
        where_short = "online" if x.get("online") else (x["city"] if x["city"] != "Location on listing" else x["country"])
        title = f"{x['title']} | {d0:%b} {d0.day}, {d0.year} | The Lineup"
        desc = (f"{x['title']} on {d0:%A, %B} {d0.day}" + (f", {where_short}" if where_short and where_short != "Unknown" else "")
                + f". {', '.join(TAG.get(t, t) for t in x['tags'])} event. " + (x.get("about") or "")[:110]).strip()
        ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", **event_ld(x)}) + "</script>"
        st = x.get("state")
        back = (f'<a class="btn" href="/us/{slug(state_names[st])}/">More in {esc(state_names[st])}</a>' if st in state_names else "")
        body = (f'<p class="when" style="margin:0 0 8px"><b style="display:inline">{esc(day)}</b> · {esc(t)}</p>'
                f"<h1>{esc(x['title'])}</h1>"
                f'<p class="lede">{esc(place or "Location on listing")}'
                f'{" · " + esc(x["cost"]) if x.get("cost") and x["cost"] != "Check listing" else ""}</p>'
                + (f'<p class="lede">{esc(x["about"])}</p>' if x.get("about") else "")
                + '<div class="cta">'
                + (f'<a class="btn btn--solid" href="{esc(x["url"])}" rel="noopener">Details and RSVP</a>' if x.get("url") else "")
                + f'<a class="btn" href="/e/{x["id"]}.ics">Add to calendar</a>{back}<a class="btn" href="/">All events</a></div>'
                + (f'<div id="going" data-event="{esc(x["id"])}" data-start="{esc(x["start"])}" data-state="{esc(st or "")}"></div>'
                   if not x.get("online") and st else "")
                + f'<div class="tags">{" · ".join(TAG.get(t, t) for t in x["tags"])} · listed via {esc(x.get("source") or "")}</div>'
                + '<script src="/acct.js?v=5" defer></script>')
        (out / sl).mkdir(parents=True, exist_ok=True)
        (out / sl / "index.html").write_text(page(title, desc[:300], f"{BASE}/event/{sl}/", body, ld))
        urls.append(f"{BASE}/event/{sl}/")
    build_static(site)
    return urls


PRIVACY = """<h1>Privacy</h1><p class="lede">Plain-English version. Last updated November 26, 2026.</p>
<h2>What we collect</h2><p>Browsing The Lineup needs no account. If you make one, we store your email, first and last name, role, experience level, optional company, which events you mark as going, and your connect requests, blocks and reports. We use privacy-friendly analytics (no ad cookies). If you use "Near me", your location stays in your browser and is never sent to us.</p>
<h2>Who sees what</h2><p>Anyone can see how many people are going to an event. Only signed-in people who are also going can see who: first name, last initial, role and experience. Your email and full last name are shared only with someone after you both accept a connect request. Your company is shown only to connections, and only if you turn it on.</p>
<h2>Emails</h2><p>With an account you get sign-in links, and (if you leave them on) an email when someone wants to connect or accepts, plus a Monday email with your home state's events. Every email has a one-click unsubscribe, and you can change these any time on your account page.</p>
<h2>Where it lives</h2><p>Account data is stored with Supabase (our database provider). Emails are sent through Resend (our email provider). We don't sell or rent your data, and we don't share it with advertisers or recruiters.</p>
<h2>Your controls</h2><p>Edit your profile, un-mark going, block people or delete your account any time from your <a href="/account/">account page</a>. Deleting your account removes your data from our database right away (backups roll off within 30 days).</p>
<h2>Age</h2><p>Accounts are for people 18 and older.</p>
<h2>Contact</h2><p>Questions or data requests: use the report button in your account or the <a href="/submit/">contact form</a>.</p>"""

TERMS = """<h1>Terms</h1><p class="lede">Last updated November 26, 2026.</p>
<h2>What this is</h2><p>The Lineup lists events organized by other people. We don't organize, host, run or vouch for any event, organizer, venue or attendee. Details can be wrong or change; always check the organizer's page.</p>
<h2>Accounts</h2><p>You must be 18 or older. Use your real name. One account per person.</p>
<h2>Be decent</h2><p>Connect requests are for professional networking at events you're actually attending. No spam, selling, recruiting blasts, harassment, or contacting people who declined or blocked you. Don't scrape or bulk-collect other users' info. We can limit or remove accounts that break these rules, and report threats to the authorities.</p>
<h2>Meeting people</h2><p>You choose who you meet and you're responsible for your own safety. Meet in the public event space. Use Block and Report if anything feels off.</p>
<h2>No warranty</h2><p>The service is provided as is, without warranties. To the extent the law allows, The Lineup isn't liable for events, other users, or losses arising from using the site.</p>
<h2>Changes</h2><p>We may update these terms; the date above will change when we do.</p>"""


def build_static(site: Path) -> None:
    for path, title, desc, body in [
        ("account", "Your account | The Lineup", "Sign in to mark events you're going to and connect with others going.",
         '<div id="account"><p class="lede">Loading…</p></div><script src="/acct.js?v=5" defer></script>'
         '<p class="meta"><a href="/privacy/">Privacy</a> · <a href="/terms/">Terms</a></p>'),
        ("unsubscribe", "Unsubscribe | The Lineup", "Stop emails from The Lineup.",
         '<h1>Email settings</h1><p class="lede" id="unsub">Working on it…</p><script src="/acct.js?v=5" defer></script>'
         '<p class="meta"><a href="/account/">Account</a> · <a href="/">All events</a></p>'),
        ("privacy", "Privacy | The Lineup", "What The Lineup collects and who can see it.", PRIVACY),
        ("terms", "Terms | The Lineup", "Rules for using The Lineup.", TERMS)]:
        (site / path).mkdir(parents=True, exist_ok=True)
        (site / path / "index.html").write_text(page(title, desc, f"{BASE}/{path}/", body))


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
            title = f'<a href="/event/{event_slug(x)}/">{e(x["title"])}</a>'
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
