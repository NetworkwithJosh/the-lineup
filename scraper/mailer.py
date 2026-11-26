"""The Lineup email robot.

  python scraper/mailer.py notices   -> connect emails ("X wants to connect", "X accepted"). Runs hourly.
  python scraper/mailer.py digest    -> Monday email: your home state's week + who's going. Runs Mondays.

Needs SUPABASE_URL, SUPABASE_SERVICE_KEY and RESEND_API_KEY (GitHub secrets). Without them it does nothing.
Add --dry to print instead of sending."""
import html, json, os, sys, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SITE = "https://thelineup.dev"
FROM = "The Lineup <hello@mail.thelineup.dev>"
ROOT = Path(__file__).resolve().parent.parent
DRY = "--dry" in sys.argv
E = html.escape
STATE_NAMES = {"AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California","CO":"Colorado","CT":"Connecticut","DE":"Delaware",
  "DC":"DC","FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky",
  "LA":"Louisiana","ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan","MN":"Minnesota","MS":"Mississippi","MO":"Missouri",
  "MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina",
  "ND":"North Dakota","OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota",
  "TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming"}
# neighbors so small states still get a useful email
NEAR = {"NJ":["NY","PA"],"NY":["NJ","CT","PA"],"CT":["NY","MA","RI"],"PA":["NJ","NY","DE","MD"],"DE":["PA","MD","NJ"],"MD":["DC","VA","DE","PA"],
  "DC":["MD","VA"],"VA":["DC","MD"],"MA":["RI","NH","CT"],"RI":["MA","CT"],"NH":["MA","ME","VT"],"VT":["NH","MA","NY"],"ME":["NH","MA"],
  "NC":["SC","VA","TN"],"SC":["NC","GA"],"GA":["SC","TN","FL","AL"],"WV":["PA","VA","OH"],"KY":["OH","TN","IN"],"MS":["TN","AL","LA"],
  "NE":["IA","KS","CO"],"ND":["MN"],"SD":["MN","IA","NE"],"WY":["CO","UT","MT"],"NM":["AZ","CO","TX"],"AK":["WA"],"HI":["CA"]}


def env(k):
    v = os.environ.get(k, "").strip()
    return v.rstrip("/") if k == "SUPABASE_URL" else v


def http(url, body=None, headers=None, method=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method=method or ("POST" if body is not None else "GET"),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        t = r.read()
        return json.loads(t) if t else None


def rpc(name, args=None):
    key = env("SUPABASE_SERVICE_KEY")
    h = {"apikey": key, **({} if key.startswith("sb_") else {"Authorization": f"Bearer {key}"})}
    return http(f"{env('SUPABASE_URL')}/rest/v1/rpc/{name}", args or {}, h)


def send(to, subject, body_html, text, unsub_url):
    msg = {"from": FROM, "to": [to], "subject": subject, "html": body_html, "text": text,
           "headers": {"List-Unsubscribe": f"<{unsub_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}}
    if DRY:
        print("----", to, "|", subject); print(text[:600]); return True
    try:
        http("https://api.resend.com/emails", msg, {"Authorization": f"Bearer {env('RESEND_API_KEY')}"})
        return True
    except Exception as exc:
        print("send failed:", to.split("@")[-1], exc, file=sys.stderr)
        return False


def shell(title, inner, unsub_url, why):
    return f"""<!doctype html><html><body style="margin:0;background:#0b0d10;padding:24px 12px;font-family:-apple-system,Segoe UI,Roboto,sans-serif">
<div style="max-width:560px;margin:0 auto;background:#12161b;border:1px solid #232a32;border-radius:12px;padding:24px;color:#e9edf1">
<div style="font-weight:600;margin-bottom:18px"><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#ffb547;margin-right:8px"></span>The Lineup</div>
<h1 style="font-size:20px;line-height:1.3;margin:0 0 14px">{E(title)}</h1>{inner}</div>
<p style="max-width:560px;margin:14px auto 0;color:#7d8996;font-size:12px;line-height:1.5;text-align:center">{E(why)}<br>
<a href="{unsub_url}" style="color:#9aa7b4">Unsubscribe</a> · <a href="{SITE}/account/" style="color:#9aa7b4">Email settings</a></p></body></html>"""


def button(href, label):
    return (f'<a href="{href}" style="display:inline-block;background:#ffb547;color:#17120a;text-decoration:none;font-weight:600;'
            f'padding:11px 18px;border-radius:8px;margin:6px 0 4px">{E(label)}</a>')


def when(iso, tz=None):
    """Event start as an aware datetime. All-day events are bare dates; treat them as noon local."""
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if len(iso) == 10:
        d = d.replace(hour=12)
    if d.tzinfo is None:
        d = d.replace(tzinfo=ZoneInfo(tz or "America/New_York"))
    return d


def nice_date(iso):
    d = when(iso).astimezone(ZoneInfo("America/New_York"))
    return f"{d:%a %b} {d.day}"


# ---------------- connect emails ----------------
def notices():
    rows = rpc("pending_connect_notices") or []
    done = defaultdict(list)
    for r in rows:
        unsub = f"{SITE}/unsubscribe/?t={r['unsub_token']}&w=notify"
        who = f"{r['other_first']} {r['other_last']}" + ("." if r["kind"] == "request" else "")
        when = nice_date(r["starts_at"])
        if r["kind"] == "request":
            subj = f"{r['other_first']} wants to connect before {r['event_title'][:60]}"
            inner = (f'<p style="color:#9aa7b4;margin:0 0 14px">Hey {E(r["to_first"])}, someone else going to '
                     f'<b style="color:#e9edf1">{E(r["event_title"])}</b> ({when}) wants to link up.</p>'
                     f'<p style="margin:0 0 4px;font-size:17px"><b>{E(who)}</b></p>'
                     f'<p style="color:#9aa7b4;margin:0 0 16px">{E(r["other_role"])} · {E(r["other_experience"])}</p>'
                     + button(f"{SITE}/account/", "Accept or decline")
                     + '<p style="color:#7d8996;font-size:13px">Nobody sees your email unless you accept.</p>')
            text = (f"Hey {r['to_first']}, {who} ({r['other_role']}, {r['other_experience']}) is going to {r['event_title']} on {when} "
                    f"and wants to connect.\nAccept or decline: {SITE}/account/\nNobody sees your email unless you accept.\n\nUnsubscribe: {unsub}")
        else:
            subj = f"You're connected with {r['other_first']} for {r['event_title'][:60]}"
            inner = (f'<p style="color:#9aa7b4;margin:0 0 14px">{E(r["other_first"])} said yes. You\'re both going to '
                     f'<b style="color:#e9edf1">{E(r["event_title"])}</b> ({when}).</p>'
                     f'<p style="margin:0 0 4px;font-size:17px"><b>{E(who)}</b></p>'
                     f'<p style="color:#9aa7b4;margin:0 0 16px">{E(r["other_role"])} · {E(r["other_experience"])}</p>'
                     + button(f"mailto:{r['other_email']}?subject=" + urllib.request.quote(f"Hey from The Lineup: {r['event_title']}"),
                              f"Say hi: {r['other_email']}")
                     + '<p style="color:#7d8996;font-size:13px">Tip: say what you\'ll be wearing or where you\'ll stand. Meet in the event space.</p>')
            text = (f"{r['other_first']} accepted. You're both going to {r['event_title']} on {when}.\n{who}, {r['other_role']}.\n"
                    f"Say hi: {r['other_email']}\n\nUnsubscribe: {unsub}")
        if send(r["to_email"], subj, shell(subj, inner, unsub, "You got this because you have connect emails on."), text, unsub):
            done[r["kind"]].append(r["id"])
    if not DRY:
        for kind, ids in done.items():
            rpc("mark_connect_notices", {"ids": ids, "kind": kind})
    print(f"notices: {sum(len(v) for v in done.values())} sent of {len(rows)}")


# ---------------- Monday digest ----------------
def digest():
    data = json.load(open(ROOT / "site" / "data" / "events.json"))
    now = datetime.now(timezone.utc)
    week = now + timedelta(days=7)
    up = [e for e in data["events"] if e.get("status") != "cancelled"
          and now <= when(e["start"], e.get("tz")) <= week]
    # going counts for these events (public numbers only)
    counts = {}
    try:
        for r in rpc("going_counts", {"ids": [e["id"] for e in up]}) or []:
            counts[r["event_id"]] = r["going"]
    except Exception as exc:
        print("going counts unavailable:", exc, file=sys.stderr)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pages import event_slug as slug  # same URLs as the site

    def row(e):
        d = when(e["start"], e.get("tz")).astimezone(ZoneInfo(e.get("tz") or "America/New_York"))
        t = "" if e.get("allDay") else f" · {d:%I:%M %p}".replace(" 0", " ")
        g = counts.get(e["id"], 0)
        going = f' · <span style="color:#ffb547">{g} going</span>' if g else ""
        where = "Online" if e.get("online") else e.get("city") or ""
        return (f'<tr><td style="padding:10px 0;border-top:1px solid #232a32;vertical-align:top;width:78px;color:#9aa7b4;font:13px monospace">{d:%a}<br>{d:%b} {d.day}</td>'
                f'<td style="padding:10px 0 10px 8px;border-top:1px solid #232a32"><a href="{SITE}/event/{slug(e)}/" style="color:#e9edf1;font-weight:600;text-decoration:none">{E(e["title"])}</a>'
                f'<div style="color:#9aa7b4;font-size:13px">{E(where)}{t}{going}</div></td></tr>')

    sent = 0
    for r in rpc("digest_recipients") or []:
        st = r["home_state"]
        local = [e for e in up if not e.get("online") and e.get("state") == st]
        nearby = [e for e in up if not e.get("online") and e.get("state") in NEAR.get(st, [])][: max(0, 6 - len(local))]
        online = [e for e in up if e.get("online")][:3]
        if not local and not nearby:
            continue  # nothing worth an email this week; skipping beats spamming
        name = STATE_NAMES.get(st, st)
        unsub = f"{SITE}/unsubscribe/?t={r['unsub_token']}&w=digest"
        subj = (f"{len(local)} meetup{'s' if len(local) != 1 else ''} in {name} this week" if local
                else f"This week near {name}: {len(nearby)} meetups close by")
        sec = lambda h, evs: (f'<p style="font:600 12px monospace;letter-spacing:.08em;text-transform:uppercase;color:#7d8996;margin:18px 0 4px">{h}</p>'
                              f'<table style="width:100%;border-collapse:collapse">{"".join(row(e) for e in evs)}</table>') if evs else ""
        inner = (f'<p style="color:#9aa7b4;margin:0 0 6px">Hey {E(r["first_name"])}, here\'s your lineup for the week.</p>'
                 + sec(f"In {name}", local[:10]) + sec("Close by", nearby) + sec("Online", online)
                 + '<p style="margin:18px 0 0">' + button(f"{SITE}/?country=United%20States&state={st}", f"See everything in {name}")
                 + '</p><p style="color:#7d8996;font-size:13px">Going to one? Tap "I\'m going" on its page. A week out you can see who else is going and connect.</p>')
        text = (f"Your lineup for the week in {name}:\n\n" + "\n".join(f"- {e['title']} ({nice_date(e['start'])}, {e.get('city') or 'online'}) {SITE}/event/{slug(e)}/"
                for e in local[:10] + nearby + online) + f"\n\nUnsubscribe: {unsub}")
        if send(r["email"], subj, shell(subj, inner, unsub, f"You got this because you picked {name} as your home state."), text, unsub):
            sent += 1
    print(f"digest: sent {sent}")


if __name__ == "__main__":
    if not (env("SUPABASE_URL") and env("SUPABASE_SERVICE_KEY") and (env("RESEND_API_KEY") or DRY)):
        print("mailer: not configured, skipping"); sys.exit(0)
    try:
        {"notices": notices, "digest": digest}[sys.argv[1]]()
    except Exception as exc:
        print("mailer failed:", exc, file=sys.stderr); sys.exit(1)
