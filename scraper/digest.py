"""Weekly email: every Monday, each subscriber gets the week's events for the state they picked.

Subscribers live in Buttondown, tagged with a two-letter state code (NJ, NY, ...) or "US" for
the whole country. This script builds one email per tag that has subscribers and events, and
hands it to Buttondown, which does the sending, unsubscribes and the legal footer.

Env:
  BUTTONDOWN_API_KEY   required
  DIGEST_MODE          "draft" (default: emails wait in Buttondown for you to press send) or "send"
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from scrape import STATE_NAMES  # noqa: E402

API = "https://api.buttondown.com/v1"
SITE = "https://thelineup.dev"
NY = ZoneInfo("America/New_York")


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(path if path.startswith("http") else API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Token {os.environ['BUTTONDOWN_API_KEY']}",
                                          "Content-Type": "application/json", "User-Agent": "the-lineup-digest"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def subscriber_tags() -> dict[str, int]:
    counts: dict[str, int] = {}
    url = "/subscribers?type=regular&page_size=100"
    while url:
        page = call("GET", url)
        for s in page.get("results", []):
            for t in s.get("tags", []):
                counts[t] = counts.get(t, 0) + 1
        url = page.get("next")
    return counts


def slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-").replace("--", "-")


def line(e: dict) -> str:
    if e["allDay"]:
        when = "All day" if e["start"] == e["end"] else f"through {date.fromisoformat(e['end']):%b} {date.fromisoformat(e['end']).day}"
    else:
        when = datetime.fromisoformat(e["start"]).strftime("%I:%M %p").lstrip("0")
    where = "Online" if e.get("online") else ", ".join(x for x in dict.fromkeys([e.get("venue"), e.get("city")])
                                                      if x and x not in ("Location on listing", "Unknown"))
    bits = " · ".join(x for x in (when, where, e.get("cost") if e.get("cost") not in (None, "", "Check listing") else "") if x)
    title = f"[{e['title']}]({e['url']})" if e.get("url") else e["title"]
    return f"- **{title}**  \n  {bits}"


def build(tag: str, events: list[dict], week_start: date) -> tuple[str, str] | None:
    week_end = week_start + timedelta(days=6)
    def in_week(e):
        s = date.fromisoformat(e["start"][:10]); en = date.fromisoformat(e["end"][:10])
        return s <= week_end and en >= week_start
    live = [e for e in events if e["status"] != "cancelled" and in_week(e)]
    local = [e for e in live if not e.get("online") and e.get("country") == "United States" and (tag == "US" or e.get("state") == tag)]
    online = [e for e in live if e.get("online")][:6]
    if not local:
        return None
    place = "the US" if tag == "US" else STATE_NAMES.get(tag, tag)
    by_day: dict[str, list[dict]] = {}
    for e in sorted(local, key=lambda x: x["start"]):
        d = date.fromisoformat(e["start"][:10])
        by_day.setdefault(f"{d:%A}, {d:%B} {d.day}", []).append(e)
    parts = [f"{len(local)} cyber, AI and IT {'event' if len(local) == 1 else 'events'} in {place} this week."]
    for day, evs in by_day.items():
        parts.append(f"### {day}\n" + "\n".join(line(e) for e in evs))
    if online:
        parts.append("### Online, anywhere\n" + "\n".join(line(e) for e in online))
    page = f"{SITE}/us/{slug(place)}/" if tag != "US" else f"{SITE}/us/"
    parts.append(f"---\nSee what you can make after work, or subscribe to the calendar: [{place} on The Lineup]({page})\n\n"
                 "The Lineup lists events other people organize. Check the organizer's page before you go.")
    subject = f"{len(local)} {'meetup' if len(local) == 1 else 'meetups'} in {place} this week ({week_start:%b} {week_start.day} to {week_end:%b} {week_end.day})"
    return subject, "\n\n".join(parts)


def main() -> int:
    if not os.environ.get("BUTTONDOWN_API_KEY"):
        print("No BUTTONDOWN_API_KEY set; nothing to send.")
        return 0
    mode = os.environ.get("DIGEST_MODE", "draft").strip().lower()
    data = json.loads((Path(__file__).parent.parent / "site" / "data" / "events.json").read_text())
    today = datetime.now(NY).date()
    week_start = today - timedelta(days=today.weekday())  # Monday
    tags = subscriber_tags()
    sent = 0
    for tag, n in sorted(tags.items()):
        if tag != "US" and tag not in STATE_NAMES:
            continue
        built = build(tag, data["events"], week_start)
        if not built:
            print(f"{tag}: {n} subscribers, no events this week, skipped")
            continue
        subject, body = built
        call("POST", "/emails", {
            "subject": subject, "body": body,
            "status": "about_to_send" if mode == "send" else "draft",
            "filters": {"predicate": "and", "groups": [],
                        "filters": [{"operator": "contains", "field": "subscriber.tags", "value": tag}]},
        })
        sent += 1
        print(f"{tag}: {n} subscribers, {'sent' if mode == 'send' else 'drafted'}: {subject}")
    print(f"{sent} digests {'sent' if mode == 'send' else 'drafted'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
