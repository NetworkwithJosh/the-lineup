"""Meetups people submit through the form on /submit/.

The Google Form writes every answer to a sheet. Only rows Josh ticks as approved are copied
(by formula) to an "Approved" tab, and only that tab is published as CSV. Submitter emails
never leave the private sheet.

A row is either
  - a group (Meetup group, Luma calendar or any .ics feed): added as a live source, so all
    of its future events show up and update on their own, or
  - a single event: added as one listing with the date, time and place given.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# column headers in the Approved tab (case-insensitive, matched by the start of the header)
COLS = {
    "kind": "what are you adding", "link": "link", "name": "name", "date": "date", "start": "start time",
    "end": "end time", "venue": "venue", "city": "city", "state": "state or country", "topic": "topic", "cost": "cost",
}
TOPIC = {"cyber": "cyber", "security": "cyber", "ai": "ai", "it": "it", "cloud": "it"}
US_TZ = {"CA": "America/Los_Angeles", "WA": "America/Los_Angeles", "OR": "America/Los_Angeles", "NV": "America/Los_Angeles",
         "AZ": "America/Phoenix", "CO": "America/Denver", "UT": "America/Denver", "NM": "America/Denver", "ID": "America/Denver",
         "MT": "America/Denver", "WY": "America/Denver", "TX": "America/Chicago", "IL": "America/Chicago", "MN": "America/Chicago",
         "WI": "America/Chicago", "MO": "America/Chicago", "IA": "America/Chicago", "KS": "America/Chicago", "NE": "America/Chicago",
         "OK": "America/Chicago", "LA": "America/Chicago", "AR": "America/Chicago", "MS": "America/Chicago", "AL": "America/Chicago",
         "TN": "America/Chicago", "ND": "America/Chicago", "SD": "America/Chicago", "HI": "Pacific/Honolulu", "AK": "America/Anchorage"}


def _col(row: dict, key: str) -> str:
    want = COLS[key]
    for k, v in row.items():
        if k and k.strip().lower().startswith(want):
            return (v or "").strip()
    return ""


def _tags(text: str) -> list[str]:
    tags = sorted({TOPIC[w] for w in re.findall(r"[a-z]+", text.lower()) if w in TOPIC})
    return tags or ["cyber"]


def _time(s: str) -> tuple[int, int] | None:
    m = re.match(r"\s*(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*([ap]\.?m\.?)?", s, re.I)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    ap = (m.group(3) or "").lower().replace(".", "")
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return h, mi


def _date(s: str) -> date | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def load(csv_text: str, place, h, us_states: set, start: date, end: date) -> tuple[dict, list[dict]]:
    """Return (extra sources in sources.json shape, single events)."""
    extra = {"meetup_groups": [], "luma_calendars": [], "ics_urls": []}
    events = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        link, name = _col(row, "link"), _col(row, "name")
        kind = _col(row, "kind").lower()
        city, region = _col(row, "city"), _col(row, "state")
        home = ", ".join(x for x in (city, region) if x)
        tags = _tags(_col(row, "topic"))
        if not (link or name):
            continue
        if "group" in kind or "calendar" in kind or "recurring" in kind:
            m = re.search(r"meetup\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", link)
            if m:
                extra["meetup_groups"].append({"slug": m.group(1), "name": name or m.group(1), "tags": tags, "home": home, "submitted": True})
                continue
            m = re.search(r"(?:lu\.ma|luma\.com)/([A-Za-z0-9_-]+)", link)
            if m:
                extra["luma_calendars"].append({"slug": m.group(1), "name": name or m.group(1), "tags": tags, "submitted": True})
                continue
            if re.search(r"\.ics(\?|$)|ical", link, re.I):
                extra["ics_urls"].append({"name": name or link, "url": link.replace("webcal://", "https://"), "page": link, "tags": tags, "home": home, "submitted": True})
                continue
            # a group with no feed we can read: skip quietly, nothing to list
            continue
        d = _date(_col(row, "date"))
        if not d or d < start or d > end:
            continue
        st = region.upper() if region.upper() in us_states else ""
        tzname = US_TZ.get(st, "America/New_York") if st else "America/New_York"
        tz = ZoneInfo(tzname)
        s, e = _time(_col(row, "start")), _time(_col(row, "end"))
        online = bool(re.search(r"online|virtual|zoom", f"{_col(row, 'venue')} {city}", re.I))
        if s:
            sdt = datetime(d.year, d.month, d.day, *s, tzinfo=tz)
            edt = datetime(d.year, d.month, d.day, *e, tzinfo=tz) if e else sdt + timedelta(hours=2)
            s_str, e_str, all_day = sdt.isoformat(timespec="minutes"), edt.isoformat(timespec="minutes"), False
        else:
            s_str = e_str = d.isoformat()
            all_day = True
        venue = _col(row, "venue")
        p = place("Online" if online else venue, home if not online else "")
        events.append({
            "id": h("submitted", re.sub(r"[^a-z0-9]+", "", (name or link).lower()), d.isoformat()),
            "title": name or link, "start": s_str, "end": e_str, "allDay": all_day, "tz": None if all_day else tzname,
            "venue": "Online" if online else (venue or p["city"]), **p,
            "format": "Online" if online else "In person", "cost": _col(row, "cost") or "Check listing",
            "tags": tags, "kind": "Meetup", "url": link, "about": "", "source": "Submitted", "status": "listed",
        })
    return extra, events
