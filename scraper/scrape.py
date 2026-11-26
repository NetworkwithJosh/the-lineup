#!/usr/bin/env python3
"""The Lineup scraper.

Pulls cybersecurity and AI events from public sources worldwide (ICS calendar
feeds, Meetup groups, Luma calendars, the confs.tech open dataset), expands
standing meetups from rules, merges hand-checked events, then compares the
result with the previous run so the site can show what is new, what changed
and what was cancelled.

Writes:
  site/data/events.json   what the website reads
  site/lineup.ics         a calendar feed people can subscribe to
                          (cancellations go out as STATUS:CANCELLED)

Standard library only. Python 3.10+.
Usage:  python scraper/scrape.py [--days 180] [--offline] [--fixture file.ics]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time as _time
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "scraper"
OUT_JSON = ROOT / "site" / "data" / "events.json"
OUT_ICS = ROOT / "site" / "lineup.ics"
UTC = timezone.utc
NY = ZoneInfo("America/New_York")
UA = "TheLineupBot/2.0 (+https://github.com/NetworkwithJosh/the-lineup; reads public calendar feeds once a day)"
WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
SCRAPER_VERSION = "2.6"  # bump when parsing rules change, so the next run re-baselines instead of reporting fake changes
NEW_DAYS = 7          # how long "New" / "Updated" badges stay up
CANCEL_KEEP_DAYS = 14  # how long a cancelled event stays on the board

CYBER_WORDS = re.compile(r"\b(cyber\w*|security|infosec|hack\w*|ctf|owasp|isaca|isc2|\(isc\)2|issa|grc|soc|threat\w*|pentest\w*|red team|blue team|privacy|zero trust|appsec|devsecops|malware|def ?con|bsides|ransomware|incident response|identity|iam|cissp|cism|wicys|infragard)\b", re.I)
IT_WORDS = re.compile(r"\b(sysadmins?|system administrat\w*|help ?desk|it support|it pros?|it professionals?|devops|sre|cloud|aws|azure|gcp|kubernetes|k8s|linux|cisco|ccna|comptia|servicenow|intune|m365|microsoft 365|active directory|entra|powershell|vmware|terraform|homelab|network engineer\w*|infrastructure|data ?center|red hat|rhel)\b", re.I)
IT_CAPS = re.compile(r"\bIT\b")


def is_it(text: str) -> bool:
    return bool(IT_WORDS.search(text) or IT_CAPS.search(text))


AI_WORDS = re.compile(r"\b(ai|a\.i\.|artificial intelligence|llms?|agents?|agentic|machine learning|ml|genai|gen ai|claude|gpt\w*|openai|anthropic|copilot|rag|mcp|deep learning|neural|nlp)\b", re.I)
ONLINE_WORDS = re.compile(r"\b(online|virtual|zoom|webinar|webcast|livestream|live stream|google meet|microsoft teams|remote|brighttalk|webex|gotowebinar|crowdcast|on24|hopin|youtube live|twitch)\b", re.I)
SKIP_TITLES = re.compile(r"\b(cfp|call for (papers|speakers|proposals)|submission deadline|deadline|hiring test|career queries|donations?|fundraiser|webinar recording|office hours for organizers)\b", re.I)

US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
COUNTRY_ALIASES = {
    "usa": "United States", "u.s.a.": "United States", "us": "United States", "u.s.": "United States",
    "united states": "United States", "united states of america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "england": "United Kingdom", "scotland": "United Kingdom",
    "wales": "United Kingdom", "great britain": "United Kingdom", "united kingdom": "United Kingdom",
    "uae": "United Arab Emirates", "the netherlands": "Netherlands", "deutschland": "Germany", "brasil": "Brazil", "españa": "Spain", "türkiye": "Turkey", "turkiye": "Turkey", "the uk": "United Kingdom", "nederland": "Netherlands", "méxico": "Mexico", "schweiz": "Switzerland", "österreich": "Austria", "italia": "Italy", "polska": "Poland", "france": "France", "japan": "Japan", "日本": "Japan",
    "ksa": "Saudi Arabia", "south korea": "South Korea", "korea": "South Korea",
}
METROS = {
    "New York area": ["new york", "nyc", "manhattan", "brooklyn", "queens", "bronx", "staten island", "jersey city",
                      "hoboken", "newark", "edison", "westfield", "perth amboy", "union", "elmwood park", "paramus",
                      "hackensack", "parsippany", "morristown", "stamford", "white plains", "long island city",
                      "iselin", "avenel", "clifton", "montclair", "wayne", "paterson", "secaucus", "fort lee", "woodbridge",
                      "summit", "weehawken", "florham park", "astoria", "yonkers", "new rochelle", "mahwah"],
    "Philadelphia area": ["philadelphia", "philly", "king of prussia", "camden"],
    "Washington DC area": ["washington", "arlington", "alexandria", "reston", "herndon", "tysons", "bethesda", "national harbor", "mclean"],
    "San Francisco Bay Area": ["san francisco", "oakland", "san jose", "palo alto", "mountain view", "santa clara", "sunnyvale", "menlo park", "berkeley"],
    "Los Angeles area": ["los angeles", "santa monica", "pasadena", "irvine", "anaheim"],
    "Boston area": ["boston", "cambridge", "somerville"],
    "London": ["london"],
}


# ---------------------------------------------------------------- fetching
def fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/calendar, application/json, text/html, */*"})
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
    v = v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    v = re.sub(r"<[^>]+>", " ", v)  # some feeds put HTML in descriptions
    return re.sub(r"[ \t]+", " ", v).strip()


def parse_dt(value: str, params: dict) -> tuple[datetime, bool, str | None]:
    """Return (aware datetime, all_day, IANA tz name if the feed named one)."""
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value[:8], "%Y%m%d").date()
        return datetime.combine(d, time(12, 0), UTC), True, None
    if value.endswith("Z"):
        return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC), False, None
    tzname = params.get("TZID", "").strip('"') or None
    try:
        tz = ZoneInfo(tzname) if tzname else UTC
    except Exception:
        tz, tzname = UTC, None
    return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=tz), False, tzname


def parse_ics(text: str) -> list[dict]:
    raw_events, cur = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur is not None:
                raw_events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            parts = head.split(";")
            params = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
            cur[parts[0].upper()] = (value, params)
    out = []
    for e in raw_events:
        if "DTSTART" not in e or "SUMMARY" not in e:
            continue
        start, all_day, tzname = parse_dt(*e["DTSTART"])
        if "DTEND" in e:
            end = parse_dt(*e["DTEND"])[0]
            if all_day:
                end -= timedelta(days=1)  # ICS all-day DTEND is exclusive
        else:
            end = start + (timedelta(0) if all_day else timedelta(hours=2))
        out.append({
            "uid": e.get("UID", ("",))[0],
            "title": unescape(e["SUMMARY"][0]),
            "start": start, "end": end, "allDay": all_day, "tzname": tzname,
            "location": unescape(e.get("LOCATION", ("",))[0]),
            "url": unescape(e.get("URL", ("",))[0]),
            "description": unescape(e.get("DESCRIPTION", ("",))[0])[:800],
            "cancelled": e.get("STATUS", ("",))[0].upper() == "CANCELLED" or bool(re.search(r"^\s*(cancel+ed)\b|\[(cancel+ed)\]", unescape(e["SUMMARY"][0]), re.I)),
        })
    return out


# ---------------------------------------------------------------- places
STATE_NAMES = {"AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California","CO":"Colorado","CT":"Connecticut","DE":"Delaware","FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi","MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota","TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming","DC":"Washington DC"}
_C = """
NY: new york, nyc, manhattan, brooklyn, queens, bronx, staten island, long island city, white plains, yonkers, albany, buffalo, rochester, syracuse, ithaca, long island, hempstead, garden city, melville, new rochelle, tarrytown, astoria
NJ: jersey city, hoboken, newark, edison, iselin, westfield, perth amboy, union, elmwood park, paramus, hackensack, parsippany, morristown, red bank, clifton, avenel, princeton, new brunswick, piscataway, trenton, camden, cherry hill, montclair, summit, secaucus, weehawken, fort lee, wayne, paterson, toms river, freehold, holmdel, somerset, bridgewater, florham park, mahwah, woodbridge, eatontown, mount laurel
CT: stamford, hartford, new haven, norwalk, greenwich, bridgeport
PA: philadelphia, philly, king of prussia, pittsburgh, harrisburg, easton, allentown, bethlehem, malvern, wayne pa, conshohocken, lancaster, state college, scranton, erie
DE: wilmington, newark de, dover
MD: baltimore, bethesda, rockville, columbia, annapolis, silver spring, gaithersburg, fort meade, laurel, national harbor, hanover
DC: washington, washington dc, washington d.c.
VA: arlington, alexandria, reston, herndon, tysons, tysons corner, mclean, fairfax, chantilly, richmond, virginia beach, norfolk, chesapeake, ashburn, leesburg, vienna va, lorton, roanoke, charlottesville
MA: boston, cambridge, somerville, worcester, waltham, burlington, lowell
RI: providence
NH: manchester nh, nashua, portsmouth
VT: burlington vt
ME: portland me
NC: raleigh, durham, charlotte, chapel hill, cary, research triangle park, greensboro, wilmington nc, asheville
SC: charleston, columbia sc, greenville
GA: atlanta, alpharetta, sandy springs, marietta, savannah, augusta, macon, dalton, norcross, duluth ga
FL: miami, tampa, orlando, jacksonville, fort lauderdale, boca raton, west palm beach, tallahassee, st. petersburg, saint petersburg, melbourne fl, sarasota, naples, gainesville, pensacola, bonita springs, cocoa beach
AL: birmingham, huntsville, montgomery, mobile
TN: nashville, memphis, knoxville, chattanooga
KY: louisville, lexington
OH: columbus, cleveland, cincinnati, dayton, akron, toledo
MI: detroit, ann arbor, grand rapids, lansing, southfield, troy, jackson mi
IN: indianapolis, fort wayne, bloomington
IL: chicago, rosemont, schaumburg, naperville, evanston, oak brook, springfield il
WI: milwaukee, madison
MN: minneapolis, st. paul, saint paul, bloomington mn
IA: des moines, west des moines, cedar rapids, iowa city
MO: st. louis, saint louis, kansas city, springfield mo
KS: wichita, overland park
NE: omaha, lincoln
OK: oklahoma city, tulsa
AR: little rock, bentonville
LA: new orleans, baton rouge
TX: dallas, houston, austin, san antonio, fort worth, plano, irving, frisco, el paso, richardson, the woodlands, round rock, arlington tx
CO: denver, boulder, colorado springs, aurora, fort collins
UT: salt lake city, lehi, provo, ogden
AZ: phoenix, scottsdale, tempe, tucson, mesa, chandler
NV: las vegas, reno, henderson
NM: albuquerque, santa fe
CA: los angeles, santa monica, pasadena, irvine, anaheim, san diego, san francisco, oakland, san jose, palo alto, mountain view, santa clara, sunnyvale, menlo park, berkeley, cupertino, sacramento, el segundo, culver city, long beach, rancho cordova, redwood city, san mateo, fremont, walnut creek, riverside, fresno, burbank, newport beach, costa mesa, south san francisco, emeryville, hollywood
OR: portland, beaverton, eugene, salem
WA: seattle, bellevue, redmond, tacoma, spokane, kirkland, everett
ID: boise
MT: bozeman, missoula
AK: anchorage
HI: honolulu
"""
CITY_STATE = {}
for line in _C.strip().splitlines():
    st, cities = line.split(":", 1)
    for c in cities.split(","):
        CITY_STATE.setdefault(c.strip(), st.strip())
AMBIGUOUS_CITIES = {"cambridge", "birmingham", "richmond", "manchester", "melbourne", "durham", "newcastle", "hamilton", "london", "perth", "windsor", "kingston", "victoria", "dover", "lincoln", "salem", "aurora", "columbia", "springfield", "wilmington", "portland", "arlington", "burlington", "lexington", "laurel", "hanover", "union", "summit", "wayne", "troy", "vienna", "naples", "frisco", "duluth", "bloomington", "georgetown"}
STATE_BY_NAME = {v.lower(): k for k, v in STATE_NAMES.items()}


def find_state(location: str, city: str, country: str) -> str:
    """Two-letter US state for an event, or "" if we can't tell or it isn't in the US."""
    if country and country not in ("United States", "Unknown"):
        return ""
    text = f"{city}, {location}"
    for part in reversed([p.strip() for p in text.split(",") if p.strip()]):
        m = re.fullmatch(r"([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?", part) or re.search(r"\b([A-Z]{2})\s+\d{5}\b", part)
        if m and m.group(1) in US_STATES:
            return m.group(1)
        low = re.sub(r"\s+\d{5}.*$", "", part.lower()).strip(" .")
        if low in STATE_BY_NAME and low not in ("washington", "new york"):
            return STATE_BY_NAME[low]
    name = re.split(r",", city or "")[0].strip().lower()
    if name in CITY_STATE and (country == "United States" or name not in AMBIGUOUS_CITIES):
        return CITY_STATE[name]
    return ""


def norm_country(s: str) -> str:
    s = s.strip().strip(".")
    if not s:
        return ""
    if s.upper() in US_STATES:
        return "United States"
    key = s.lower().replace(".", "").strip()
    return COUNTRY_ALIASES.get(key, COUNTRY_ALIASES.get(s.lower(), s))


CITY_HINTS = {
    "New York": "United States", "Brooklyn": "United States", "Jersey City": "United States", "Philadelphia": "United States",
    "Boston": "United States", "Washington": "United States", "Arlington": "United States", "Baltimore": "United States",
    "Atlanta": "United States", "Miami": "United States", "Tampa": "United States", "Orlando": "United States",
    "Chicago": "United States", "Detroit": "United States", "Minneapolis": "United States", "Dallas": "United States",
    "Houston": "United States", "Austin": "United States", "San Antonio": "United States", "Denver": "United States",
    "Phoenix": "United States", "Las Vegas": "United States", "Los Angeles": "United States", "San Diego": "United States",
    "San Francisco": "United States", "San Jose": "United States", "Seattle": "United States", "Portland": "United States",
    "Raleigh": "United States", "Charlotte": "United States", "Nashville": "United States", "Pittsburgh": "United States",
    "Toronto": "Canada", "Montreal": "Canada", "Vancouver": "Canada", "Ottawa": "Canada", "Calgary": "Canada",
    "London": "United Kingdom", "Manchester": "United Kingdom", "Edinburgh": "United Kingdom", "Dublin": "Ireland",
    "Paris": "France", "Lyon": "France", "Berlin": "Germany", "Munich": "Germany", "Hamburg": "Germany", "Frankfurt": "Germany",
    "Amsterdam": "Netherlands", "Brussels": "Belgium", "Madrid": "Spain", "Barcelona": "Spain", "Lisbon": "Portugal",
    "Rome": "Italy", "Milan": "Italy", "Zurich": "Switzerland", "Geneva": "Switzerland", "Vienna": "Austria",
    "Stockholm": "Sweden", "Oslo": "Norway", "Copenhagen": "Denmark", "Helsinki": "Finland", "Warsaw": "Poland",
    "Prague": "Czechia", "Athens": "Greece", "Istanbul": "Turkey", "Tel Aviv": "Israel", "Dubai": "United Arab Emirates",
    "Abu Dhabi": "United Arab Emirates", "Riyadh": "Saudi Arabia", "Doha": "Qatar", "Cairo": "Egypt", "Lagos": "Nigeria",
    "Nairobi": "Kenya", "Johannesburg": "South Africa", "Cape Town": "South Africa", "Mumbai": "India", "Bengaluru": "India",
    "Bangalore": "India", "Delhi": "India", "New Delhi": "India", "Hyderabad": "India", "Pune": "India", "Chennai": "India",
    "Singapore": "Singapore", "Kuala Lumpur": "Malaysia", "Jakarta": "Indonesia", "Manila": "Philippines", "Bangkok": "Thailand",
    "Hong Kong": "Hong Kong", "Tokyo": "Japan", "Seoul": "South Korea", "Sydney": "Australia", "Melbourne": "Australia",
    "Brisbane": "Australia", "Auckland": "New Zealand", "Sao Paulo": "Brazil", "São Paulo": "Brazil", "Mexico City": "Mexico",
    "Bogota": "Colombia", "Buenos Aires": "Argentina", "Santiago": "Chile", "Lima": "Peru", "Panama City": "Panama",
}
COUNTRY_HINTS = ["United States", "Canada", "United Kingdom", "Ireland", "France", "Germany", "Netherlands", "Belgium", "Spain",
                 "Portugal", "Italy", "Switzerland", "Austria", "Sweden", "Norway", "Denmark", "Finland", "Poland", "Greece",
                 "Turkey", "Israel", "Egypt", "Nigeria", "Kenya", "South Africa", "India", "Pakistan", "Singapore", "Malaysia",
                 "Indonesia", "Philippines", "Thailand", "Vietnam", "Japan", "South Korea", "Australia", "New Zealand", "Brazil",
                 "Mexico", "Colombia", "Argentina", "Chile", "Peru", "Saudi Arabia", "Qatar", "Tunisia", "Morocco", "Romania",
                 "Ukraine", "Estonia", "Lithuania", "Latvia", "Hungary", "Czechia", "Luxembourg", "Panama", "Costa Rica",
                 "Middle East", "Europe", "BeNeLux", "Benelux", "LATAM", "Africa", "Asia"]
REGION_WORDS = {"Middle East", "Europe", "BeNeLux", "Benelux", "LATAM", "Africa", "Asia"}


def hint_place(text: str) -> tuple[str, str]:
    """Find a city or country named in a title or description."""
    for city, country in sorted(CITY_HINTS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![A-Za-z]){re.escape(city)}(?![A-Za-z])", text):
            return city, country
    for country in COUNTRY_HINTS:
        if re.search(rf"(?<![A-Za-z]){re.escape(country)}(?![A-Za-z])", text):
            return "", "" if country in REGION_WORDS else country
    return "", ""


_KNOWN: set = set()


def known_countries() -> set:
    if not _KNOWN:
        _KNOWN.update(c for c in COUNTRY_HINTS if c not in REGION_WORDS)
        _KNOWN.update(CITY_HINTS.values())
        _KNOWN.update(COUNTRY_ALIASES.values())
        _KNOWN.update(["Hong Kong", "Taiwan", "China", "Croatia", "Serbia", "Bulgaria", "Slovakia", "Slovenia", "Iceland",
                       "Cyprus", "Malta", "Bahrain", "Kuwait", "Oman", "Jordan", "Lebanon", "Ghana", "Rwanda", "Uganda",
                       "Ethiopia", "Bangladesh", "Sri Lanka", "Nepal", "Uruguay", "Ecuador", "Dominican Republic",
                       "Puerto Rico", "Jamaica", "Gibraltar", "Monaco", "Georgia", "Armenia", "Kazakhstan", "Uzbekistan"])
    return _KNOWN


PLACEHOLDER_LOC = re.compile(r"check (the )?event page|location on listing|register to see|link visible|details to follow|\btbd\b|\btba\b|to be announced|see description", re.I)


def place(location: str, city: str = "", country: str = "") -> dict:
    """Work out city, country and metro from whatever the source gives us."""
    location = re.sub(r"\s+", " ", location or "").strip()
    if ONLINE_WORDS.search(location) or ONLINE_WORDS.search(city) or (city or "").lower() == "online":
        return {"online": True, "city": "Online", "country": "Online", "metro": "Online", "state": ""}
    parts = [p.strip() for p in location.split(",") if p.strip()]
    if country:
        country = norm_country(country)
    elif city and "," in city:
        country = norm_country(city.rsplit(",", 1)[1])
    elif parts:
        for part in reversed(parts):
            m = re.search(r"\b([A-Z]{2})\b(?:\s+\d{5}(-\d{4})?)?$", part)
            if m and m.group(1) in US_STATES:
                country = "United States"
                break
            cleaned = re.sub(r"\b\d{3,6}(-\d{4})?\b", "", part).strip()
            if cleaned.lower() in STATE_BY_NAME:
                country = "United States"
                break
            if cleaned and not re.search(r"\d", cleaned) and norm_country(cleaned) in known_countries():
                country = norm_country(cleaned)
                break
    if not country and location and not city:
        hc, hco = hint_place(location)
        if hc:
            city, country = hc, hco
        elif hco:
            country = hco
    if not city:
        # "Venue, 123 Street, City, ST 10001, United States" -> City
        cands = [p for p in parts if not re.search(r"\d", p) and norm_country(p) != country and p.upper() not in US_STATES
                 and p.lower() not in STATE_BY_NAME]
        named = [p for p in cands if p.lower() in CITY_STATE or p in CITY_HINTS]
        hc = hint_place(location)[0] if location else ""
        city = named[-1] if named else (hc or (cands[-1] if cands else ""))
    city_name = re.split(r",", city)[0].strip()
    low = city_name.lower()
    metro = city_name
    if country in ("", "United States") or (country == "United Kingdom" and low == "london"):
        metro = next((m for m, names in METROS.items() if low in names), city_name)
    if not country and metro in METROS and metro not in ("London",):
        country = "United States"
    if metro == "London" and not country:
        country = "United Kingdom"
    st = find_state(location, city, country)
    if st and not country:
        country = "United States"
    return {"online": False, "city": city_name or "Location on listing", "country": country or "Unknown", "metro": metro or city_name,
            "state": st if country == "United States" else ""}


# ---------------------------------------------------------------- shaping
def tags_for(text: str, base: list[str]) -> list[str]:
    tags = set(base)
    if CYBER_WORDS.search(text):
        tags.add("cyber")
    if AI_WORDS.search(text):
        tags.add("ai")
    if is_it(text):
        tags.add("it")
    return sorted(tags)


def guess_cost(text: str) -> str:
    if re.search(r"\bfree\b", text, re.I):
        return "Free"
    m = re.search(r"(?:\$|€|£)\s?\d[\d,]*(\.\d\d)?", text)
    return m.group(0).replace(" ", "") if m else "Check listing"


def h(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def iso_local(dt: datetime, all_day: bool, tzname: str | None) -> str:
    if all_day:
        return dt.date().isoformat()
    return dt.astimezone(ZoneInfo(tzname) if tzname else UTC).isoformat(timespec="minutes")


STREET = re.compile(r"\b\d{1,5}\s+(?:[NSEW]\.?\s+)?[A-Z0-9][\w.'-]*(?:\s+[\w.'-]+){0,4}\s+(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Way|Pl|Place|Ln|Lane|Pkwy|Parkway|Hwy|Highway|Sq|Square|Ct|Court|Plaza)\b\.?"
                    r"(?:[^\n,]{0,30})?,\s*[A-Z][A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Z][a-z]+(?: [A-Z][a-z]+)?)(?:\s+\d{5}(?:-\d{4})?)?")


def tidy_about(text: str) -> str:
    """Readable one-paragraph blurb from an event description full of markdown, links and boilerplate."""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)            # images
    t = re.sub(r"\[([^\]]+)\]\((?:[^)]*)\)", r"\1", t)          # [text](link) -> text
    t = re.sub(r"https?://\S+", " ", t)                           # bare links
    t = re.sub(r"(?im)^(event data from|source|event details|hosted by|get up-to-date information at)\b.*$", " ", t)
    t = re.sub(r"[#*_>|`]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -:·")
    if len(t) > 220:
        cut = t[:220]
        t = (cut[:cut.rfind(" ")] if " " in cut else cut).rstrip(",;:-") + "…"
    return t


def shape_feed_event(e: dict, src: dict, source_name: str, uid_counts: Counter) -> dict | None:
    if src.get("skip_titles") and re.search(src["skip_titles"], e["title"], re.I):
        return None
    if src.get("keep_titles") and not re.search(src["keep_titles"], e["title"], re.I):
        return None
    if SKIP_TITLES.search(e["title"]):
        return None
    e = {**e, "title": re.sub(r"\s*[\u2014\u2013-]+\s*Conference Dates\s*$", "", e["title"]).strip()}
    text = f"{e['title']} {e['description']} {e['location']}"
    tags = tags_for(text, [] if src.get("require_keywords") else src.get("tags", []))
    if src.get("require_keywords"):
        if not (CYBER_WORDS.search(text) or AI_WORDS.search(text) or is_it(text)):
            return None
        tags = sorted(set(tags) | set(src.get("tags", [])))
    if not tags:
        return None
    loc = e["location"]
    url = e["url"]
    if loc.startswith("http"):
        url, loc = url or loc, ""
    if PLACEHOLDER_LOC.search(loc):
        loc = ""
    m = re.search(r"(?:Address|Location|Where)\s*:\s*([^\n]+)", e["description"])
    if not loc and m:
        loc = m.group(1).strip()
    if PLACEHOLDER_LOC.search(loc):
        loc = ""
    if not loc:  # no location field: look for a street address written in the description
        sm = STREET.search(e["description"])
        if sm:
            loc = sm.group(0).strip()
    p = place(loc)
    if not loc and ONLINE_WORDS.search(e["title"]):
        p = place("Online")  # no venue and the title says webinar/virtual/online: don't pin it to the group's home city
    if p["country"] == "Unknown" or p["city"] == "Location on listing":
        # A place named in the TITLE wins. Then the group's home city. Only then cities mentioned in the
        # description, which often name somewhere else entirely ("DEF CON started in Las Vegas...").
        texts = [e["title"]] + ([] if src.get("home") else [f"{e['title']} {e['description'][:300]}"])
        for t in texts:
            hc, hco = hint_place(t)
            if hc or hco:
                p = place("", hc or "", hco) if hc else {**p, "country": hco, "city": "Location on listing", "metro": "Location on listing", "state": ""}
                break
    if (p["country"] == "Unknown" or p["city"] == "Location on listing") and src.get("home"):
        p = place("", src["home"])  # a local group's events default to its home city
    if src.get("drop_unplaced") and not p["online"] and (p["country"] == "Unknown" or p["city"] == "Location on listing"):
        return None  # big global calendars: an event we can't place on a map isn't useful to anyone
    uid = e["uid"] or norm_title(e["title"])
    key = uid if uid_counts[uid] <= 1 else f"{uid}{e['start'].date()}"
    return {
        "id": h(source_name, key),
        "title": re.sub(r"\s*\[(cancel+ed)\]\s*", " ", re.sub(r"^\s*cancel+ed\s*[:\-]\s*", "", e["title"], flags=re.I), flags=re.I).strip(),
        "start": iso_local(e["start"], e["allDay"], e["tzname"]),
        "end": iso_local(e["end"], e["allDay"], e["tzname"]),
        "allDay": e["allDay"],
        "tz": e["tzname"],
        "venue": "Online" if p["online"] else (loc.split(",")[0].strip() if loc else "Location on listing"),
        **p,
        "format": "Online" if p["online"] else "In person",
        "cost": guess_cost(text),
        "tags": tags,
        "kind": "Conference" if e["allDay"] and e["end"].date() > e["start"].date() else ("Event" if e["allDay"] else "Meetup"),
        "url": url or src.get("page", ""),
        "about": tidy_about(e["description"]),
        "source": source_name,
        "status": "cancelled" if e["cancelled"] else "listed",
        "cancelReason": "Cancelled by the organizer" if e["cancelled"] else None,
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
            tz = ZoneInfo(r.get("tz", "America/New_York"))
            hs, ms = map(int, r["start"].split(":"))
            he, me = map(int, r["end"].split(":"))
            s = datetime.combine(d, time(hs, ms), tz)
            e = datetime.combine(d, time(he, me), tz)
            out.append({
                "id": h("standing", r["title"], d.isoformat()), "title": r["title"],
                "start": s.isoformat(timespec="minutes"), "end": e.isoformat(timespec="minutes"),
                "allDay": False, "tz": r.get("tz", "America/New_York"),
                "venue": r["venue"], **place(r["venue"], r["city"]),
                "format": r["format"], "cost": r["cost"], "tags": r["tags"], "kind": r["kind"],
                "url": r["url"], "about": r["about"], "source": "Standing meetup", "status": "recurring",
            })
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def load_curated(start: date, end: date) -> list[dict]:
    out = []
    for c in json.loads((CFG / "curated.json").read_text())["events"]:
        all_day = len(c["start"]) == 10
        tzname = c.get("tz", "America/New_York")
        tz = ZoneInfo(tzname)
        if all_day:
            s_date, e_date = date.fromisoformat(c["start"]), date.fromisoformat(c["end"])
            s_str, e_str = c["start"], c["end"]
        else:
            s_dt = datetime.fromisoformat(c["start"]).replace(tzinfo=tz)
            e_dt = datetime.fromisoformat(c["end"]).replace(tzinfo=tz)
            s_date, e_date = s_dt.date(), e_dt.date()
            s_str, e_str = s_dt.isoformat(timespec="minutes"), e_dt.isoformat(timespec="minutes")
        if e_date < start or s_date > end:
            continue
        ev = {k: c[k] for k in ("title", "venue", "format", "cost", "tags", "kind", "url", "about")}
        ev.update(place(c["venue"], c["city"], c.get("country", "")))
        ev.update({"id": h("curated", norm_title(c["title"])), "start": s_str, "end": e_str, "allDay": all_day,
                   "tz": tzname, "source": "Checked by hand", "status": c.get("status", "confirmed")})
        out.append(ev)
    return out


# ---------------------------------------------------------------- sources
def pull_ics_sources(sources: dict, start: date, end: date, report: list) -> list[dict]:
    jobs = []
    for u in sources.get("ics_urls", []):
        jobs.append((u, u["url"], u["name"]))
    for g in sources.get("meetup_groups", []):
        sl = urllib.parse.quote(g["slug"], safe="-_")
        jobs.append(({**g, "page": f"https://www.meetup.com/{sl}/events/"}, f"https://www.meetup.com/{sl}/events/ical/", g["name"]))
    for c in sources.get("luma_calendars", []):
        jobs.append(({**c, "page": f"https://luma.com/{c['slug']}"}, None, c["name"]))
    def grab(job):
        src, url, name = job
        last = None
        for attempt in range(3):  # Meetup sometimes answers 403/429 when hit fast; back off and retry
            try:
                if url is None:  # Luma: find the calendar id on its public page, then use its ICS feed
                    m = re.search(r"\bcal-[A-Za-z0-9]{8,}\b", fetch(src["page"]))
                    if not m:
                        raise ValueError("calendar id not found on page")
                    return parse_ics(fetch(f"https://api.lu.ma/ics/get?entity=calendar&id={m.group(0)}")), None
                return parse_ics(fetch(url)), None
            except Exception as exc:
                last = exc
                if "404" in str(exc) or "calendar id" in str(exc):
                    break
                _time.sleep(2 + attempt * 3)
        return None, last

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(grab, jobs))
    out = []
    for (src, url, name), (evs, err) in zip(jobs, results):
        if evs is None and "meetup.com" in (url or "") and "404" in str(err):
            # Meetup answers 404 for a group's calendar when it has nothing posted yet. Not broken: keep following it.
            report.append({"source": name, "ok": True, "events": 0, "note": "no upcoming events posted"})
            continue
        if evs is None:  # one dead feed never breaks the run
            report.append({"source": name, "ok": False, "error": str(err)[:140]})
            continue
        uid_counts = Counter(e["uid"] for e in evs if e["uid"])
        kept = 0
        for e in evs:
            if e["end"].date() < start or e["start"].date() > end:
                continue
            shaped = shape_feed_event(e, src, name, uid_counts)
            if shaped:
                out.append(shaped)
                kept += 1
        report.append({"source": name, "ok": True, "events": kept})
    return out


def pull_confs_tech(cfg: dict, start: date, end: date, report: list) -> list[dict]:
    out = []
    for t in cfg.get("topics", []):
        name = f"confs.tech: {t['topic']}"
        try:
            kept = 0
            for year in sorted({start.year, end.year}):
                try:
                    data = json.loads(fetch(f"{cfg['base']}/{year}/{t['topic']}.json"))
                except urllib.error.HTTPError as exc:
                    if exc.code == 404:
                        continue
                    raise
                for c in data:
                    s, e = date.fromisoformat(c["startDate"]), date.fromisoformat(c.get("endDate") or c["startDate"])
                    if e < start or s > end:
                        continue
                    text = f"{c['name']} {c.get('url', '')}"
                    if t.get("require_keywords") and not (CYBER_WORDS.search(text) or AI_WORDS.search(text) or is_it(text)):
                        continue
                    tags = tags_for(text, t.get("tags", []))
                    if not tags:
                        continue
                    online_only = c.get("online") and not c.get("city")
                    p = place("Online" if online_only else "", c.get("city", ""), "" if online_only else c.get("country", ""))
                    out.append({
                        "id": h("confs", norm_title(c["name"]), str(s.year)), "title": c["name"],
                        "start": s.isoformat(), "end": e.isoformat(), "allDay": True, "tz": None,
                        "venue": "Online" if p["online"] else p["city"], **p,
                        "format": "Online" if p["online"] else ("In person + online" if c.get("online") else "In person"),
                        "cost": "Check listing", "tags": tags, "kind": "Conference" if e > s else "Event",
                        "url": c.get("url", ""), "about": "", "source": "confs.tech", "status": "listed",
                    })
                    kept += 1
            report.append({"source": name, "ok": True, "events": kept})
        except Exception as exc:
            report.append({"source": name, "ok": False, "error": str(exc)[:140]})
    return out


# ---------------------------------------------------------------- dedupe
STOP = {"the", "and", "for", "with", "meetup", "meeting", "event", "events", "monthly", "chapter", "edition", "annual", "official",
        "2026", "2027", "nyc", "new", "york", "online", "virtual", "in-person", "night", "session"}


def title_tokens(t: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2 and w not in STOP}


def same_event(a: dict, b: dict) -> bool:
    pa, pb = (a.get("metro") or ""), (b.get("metro") or "")
    unknown = {"Location on listing", "", "Unknown"}
    if a.get("online") != b.get("online") or not (pa == pb or pa in unknown or pb in unknown):
        return False  # same name in two different cities is two events
    na, nb = norm_title(a["title"]), norm_title(b["title"])
    if na[:28] == nb[:28]:
        return True
    if min(len(na), len(nb)) >= 14 and (na in nb or nb in na):
        return True
    ta, tb = title_tokens(a["title"]), title_tokens(b["title"])
    close = len(ta) >= 3 and len(tb) >= 3 and len(ta & tb) / len(ta | tb) >= 0.6
    nested = min(len(ta), len(tb)) >= 2 and (ta <= tb or tb <= ta)
    return close or nested


def dedupe(events: list[dict]) -> list[dict]:
    """Merge the same event listed by several sources. Keeps the most trustworthy copy."""
    rank = {"confirmed": 4, "listed": 3, "verify": 2, "recurring": 1, "cancelled": 0}

    def score(e):
        return (rank.get(e["status"], 0), e.get("city") not in ("Location on listing", "", None), bool(e.get("about")), bool(e.get("tz")))

    by_day: dict[str, list[dict]] = {}
    for e in sorted(events, key=score, reverse=True):
        day = by_day.setdefault(e["start"][:10], [])
        if any(same_event(e, k) for k in day):
            continue
        day.append(e)
    return [e for day in by_day.values() for e in day]


# ---------------------------------------------------------------- change tracking
def fmt_when(e: dict) -> str:
    if e["allDay"]:
        s, en = date.fromisoformat(e["start"]), date.fromisoformat(e["end"])
        if s == en:
            return f"{s:%b} {s.day}"
        return f"{s:%b} {s.day} to {en.day}" if s.month == en.month else f"{s:%b} {s.day} to {en:%b} {en.day}"
    d = datetime.fromisoformat(e["start"])
    return f"{d:%b} {d.day} at {d.strftime('%I:%M %p').lstrip('0')}"


def track_changes(current: list[dict], prev: dict | None, failed_sources: set, now: datetime) -> tuple[list[dict], str, dict]:
    """Stamp each event with firstSeen / changes / cancellations relative to the previous run."""
    now_s = now.isoformat(timespec="minutes")
    if not prev or "baselineAt" not in prev or prev.get("scraperVersion") != SCRAPER_VERSION:
        # First tracked run, or the scraper's rules changed: start a fresh comparison.
        baseline = now_s
        old_seen = {e["id"]: e for e in (prev or {}).get("events", [])}
        for e in current:
            o = old_seen.get(e["id"], {})
            e.update({"firstSeen": o.get("firstSeen", now_s), "seq": o.get("seq", 0)})
            if e["status"] == "cancelled":
                e["cancelledAt"] = o.get("cancelledAt", now_s)
        return current, baseline, {"new": 0, "updated": 0, "cancelled": 0}

    baseline = prev["baselineAt"]
    old = {e["id"]: e for e in prev.get("events", [])}
    today = now.date()
    cutoff = (now - timedelta(days=NEW_DAYS)).isoformat(timespec="minutes")
    stats = Counter()

    seen_ids = set()
    for e in current:
        seen_ids.add(e["id"])
        o = old.get(e["id"])
        if not o:
            e.update({"firstSeen": now_s, "seq": 0})
            if e["status"] == "cancelled":
                e["cancelledAt"] = now_s
            continue
        e["firstSeen"] = o.get("firstSeen", baseline)
        e["seq"] = o.get("seq", 0)
        changes = []
        if (e["start"], e["end"]) != (o["start"], o["end"]):
            changes.append(f"Now {fmt_when(e)} (was {fmt_when(o)})")
        if e.get("venue") != o.get("venue") and o.get("venue") and e["status"] != "cancelled":
            changes.append(f"New venue: {e['venue']}")
        if o.get("status") == "cancelled" and e["status"] != "cancelled":
            changes.append("Back on after being cancelled")
        if e["status"] == "cancelled" and o.get("status") != "cancelled":
            e["cancelledAt"] = now_s
            e["seq"] += 1
        elif e["status"] == "cancelled":
            e["cancelledAt"] = o.get("cancelledAt", now_s)
        if changes:
            e.update({"changes": changes, "changedAt": now_s, "seq": e["seq"] + 1})
        elif o.get("changedAt", "") >= cutoff:
            e.update({"changes": o.get("changes", []), "changedAt": o["changedAt"]})

    # Events that were on the board last run and are gone now.
    for oid, o in old.items():
        if oid in seen_ids:
            continue
        start_d = date.fromisoformat(o["start"][:10])
        if start_d < today:
            continue  # it simply happened
        if o["source"] in failed_sources:
            current.append(o)  # feed was down this run: keep it as it was, never call it cancelled
            continue
        cancelled_at = o.get("cancelledAt") or now_s
        if o.get("status") == "cancelled" and cancelled_at < (now - timedelta(days=CANCEL_KEEP_DAYS)).isoformat():
            continue
        o = {**o, "status": "cancelled", "cancelledAt": cancelled_at,
             "cancelReason": o.get("cancelReason") or "No longer listed by the organizer",
             "seq": o.get("seq", 0) + (0 if o.get("status") == "cancelled" else 1)}
        current.append(o)

    for e in current:
        if e["status"] == "cancelled" and e.get("cancelledAt", "") >= cutoff:
            stats["cancelled"] += 1
        elif e["status"] != "recurring" and e.get("firstSeen", "") > baseline and e["firstSeen"] >= cutoff:
            stats["new"] += 1
        elif e.get("changedAt", "") >= cutoff:
            stats["updated"] += 1
    return current, baseline, dict(stats)


# ---------------------------------------------------------------- output
def ics_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def write_ics(events: list[dict], stamp: datetime, single: bool = False) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//The Lineup//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    if not single:
        lines += ["X-WR-CALNAME:The Lineup: cyber, AI + IT meetups", "REFRESH-INTERVAL;VALUE=DURATION:P1D", "X-PUBLISHED-TTL:P1D"]
    for e in events:
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@the-lineup", f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}", f"SEQUENCE:{e.get('seq', 0)}"]
        if e["allDay"]:
            s = date.fromisoformat(e["start"]); en = date.fromisoformat(e["end"]) + timedelta(days=1)
            lines += [f"DTSTART;VALUE=DATE:{s:%Y%m%d}", f"DTEND;VALUE=DATE:{en:%Y%m%d}"]
        else:
            s = datetime.fromisoformat(e["start"]).astimezone(UTC)
            en = datetime.fromisoformat(e["end"]).astimezone(UTC)
            lines += [f"DTSTART:{s:%Y%m%dT%H%M%SZ}", f"DTEND:{en:%Y%m%dT%H%M%SZ}"]
        loc = "Online" if e.get("online") else ", ".join(x for x in (e["venue"], e["city"], e["country"]) if x and x not in ("Unknown",))
        title = ("CANCELLED: " if e["status"] == "cancelled" else "") + e["title"]
        desc = " ".join(x for x in ((e.get("cancelReason") or "") if e["status"] == "cancelled" else "", e.get("about", ""), e.get("url", "")) if x)
        lines += [f"SUMMARY:{ics_escape(title)}", f"LOCATION:{ics_escape(loc)}", f"DESCRIPTION:{ics_escape(desc)}",
                  f"STATUS:{'CANCELLED' if e['status'] == 'cancelled' else 'CONFIRMED'}"]
        if e.get("url"):
            lines.append(f"URL:{e['url']}")
        if single:
            lines += ["BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY", "DESCRIPTION:Tomorrow", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180, help="how far ahead to look")
    ap.add_argument("--offline", action="store_true", help="skip network sources (hand-checked + standing only)")
    ap.add_argument("--fixture", action="append", default=[], help="parse a local .ics as an extra feed (testing)")
    ap.add_argument("--now", help="pretend it is this ISO time (testing)")
    args = ap.parse_args()

    now = datetime.fromisoformat(args.now).astimezone(NY) if args.now else datetime.now(NY)
    start, end = now.date(), now.date() + timedelta(days=args.days)
    sources = json.loads((CFG / "sources.json").read_text())
    disc = CFG / "discovered.json"  # groups found automatically by discover.py (weekly); hand-picked ones win
    if disc.exists():
        mine = {g["slug"].lower() for g in sources["meetup_groups"]}
        d = json.loads(disc.read_text())
        blocked = {b.lower() for b in d.get("blocked", [])}
        sources["meetup_groups"] += [g for g in d.get("groups", []) if g["slug"].lower() not in mine | blocked]
    rules = json.loads((CFG / "recurring.json").read_text())["rules"]
    prev = json.loads(OUT_JSON.read_text()) if OUT_JSON.exists() else None
    report: list = []

    events = load_curated(start, end) + expand_rules(rules, start, end)
    for fx in args.fixture:
        evs = parse_ics(Path(fx).read_text())
        uc = Counter(e["uid"] for e in evs if e["uid"])
        for e in evs:
            if e["end"].date() >= start:
                shaped = shape_feed_event(e, {"tags": [], "page": ""}, "Fixture feed", uc)
                if shaped:
                    events.append(shaped)
        report.append({"source": "Fixture feed", "ok": True})
    if not args.offline and sources.get("submissions_csv"):
        import submissions  # approved community submissions from the /submit/ form
        try:
            extra, single = submissions.load(fetch(sources["submissions_csv"]), place, h, US_STATES, start, end)
            known = {k: {(x.get("slug") or x.get("url", "")).lower() for x in sources.get(k, [])} for k in extra}
            for k, items in extra.items():
                sources.setdefault(k, []).extend(x for x in items if (x.get("slug") or x.get("url", "")).lower() not in known[k])
            events += single
            report.append({"source": "Community submissions", "ok": True, "events": len(single),
                           "groups": sum(len(v) for v in extra.values())})
        except Exception as exc:
            report.append({"source": "Community submissions", "ok": False, "error": str(exc)[:140]})
    if not args.offline:
        events += pull_ics_sources(sources, start, end, report)
        events += pull_confs_tech(sources.get("confs_tech", {}), start, end, report)
        try:
            import eventbrite, discover  # cyber events on Eventbrite, one search per state
            events += eventbrite.pull(discover.CITIES, start, end, place, report, prev_events=(prev or {}).get("events"), half=now.hour // 12 % 2)
        except Exception as exc:
            report.append({"source": "Eventbrite", "ok": False, "error": str(exc)[:140]})

    failed = {r["source"] for r in report if not r.get("ok")}
    if args.offline and prev:  # offline test runs must not cancel feed events
        failed |= {e["source"] for e in prev.get("events", [])} - {"Checked by hand", "Standing meetup", "Fixture feed"}
    events = dedupe(events)
    if not args.offline:
        import enrich  # full / waitlist status and real online flag from each Meetup event page
        try:
            enrich.attach(events, (prev or {}).get("events"), now, sources.get("luma_calendars"))
        except Exception as exc:
            print("enrich skipped:", exc)
    import geo  # coordinates for "Near me", one cached lookup per city
    geo.attach(events, offline=args.offline)
    events, baseline, stats = track_changes(events, prev, failed, now)
    events.sort(key=lambda e: (e["start"][:10], e["start"], e["title"]))

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generatedAt": now.isoformat(timespec="minutes"), "baselineAt": baseline, "scraperVersion": SCRAPER_VERSION, "windowDays": args.days,
               "count": sum(1 for e in events if e["status"] != "cancelled"), "changes": stats,
               "sources": report, "events": events}
    OUT_JSON.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    OUT_ICS.write_text(write_ics(events, datetime.now(UTC)))
    # one small .ics per event: phones open a real file URL far more reliably than a JS download
    one_dir = ROOT / "site" / "e"
    one_dir.mkdir(exist_ok=True)
    keep = set()
    for e in events:
        if e["status"] != "cancelled":
            f = one_dir / f"{e['id']}.ics"
            f.write_text(write_ics([e], datetime.now(UTC), single=True))
            keep.add(f.name)
    for f in one_dir.glob("*.ics"):
        if f.name not in keep:
            f.unlink()
    import pages  # per-state pages and feeds
    state_urls = pages.build(events, STATE_NAMES, write_ics, datetime.now(UTC), ROOT / "site")
    event_urls = pages.build_events(events, STATE_NAMES, datetime.now(UTC), ROOT / "site")
    urls = ["https://thelineup.dev/", "https://thelineup.dev/submit/", "https://thelineup.dev/organizers/"] + state_urls + event_urls
    (ROOT / "site" / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc><lastmod>{now.date().isoformat()}</lastmod><changefreq>daily</changefreq></url>\n" for u in urls)
        + "</urlset>\n")
    ok = sum(1 for r in report if r.get("ok"))
    print(f"{payload['count']} events ({stats}). Sources ok: {ok}/{len(report)}")
    for r in report:
        if not r.get("ok"):
            print(f"  source failed: {r['source']}: {r.get('error') or r.get('note', '')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
