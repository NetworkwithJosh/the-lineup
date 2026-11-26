"""Sunday email to the site owner: where coverage is thin, what users flagged, what discovery found.
Needs REPORT_TO (GitHub variable) plus the same Supabase/Resend secrets as the mailer. Does nothing without them."""
import json, os, sys
from datetime import date, datetime, timedelta, timezone
from html import escape as E
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mailer  # reuse its Supabase + Resend helpers

STATES = mailer.STATE_NAMES


def main():
    to = os.environ.get("REPORT_TO", "").strip()
    if not to:
        print("coverage: REPORT_TO not set, skipping"); return
    data = json.loads((HERE.parent / "site" / "data" / "events.json").read_text())
    now = datetime.now(timezone.utc)
    soon = [e for e in data["events"] if e.get("status") != "cancelled" and not e.get("online")
            and mailer.when(e["start"], e.get("tz")) <= now + timedelta(days=60)]
    per = {st: 0 for st in STATES}
    for e in soon:
        if e.get("country") == "United States" and e.get("state") in per:
            per[e["state"]] += 1
    empty = sorted(STATES[s] for s, n in per.items() if n == 0)
    thin = sorted(f"{STATES[s]} ({n})" for s, n in per.items() if 0 < n <= 2)
    quiet = [s["source"] for s in data.get("sources", []) if s.get("ok") and not s.get("events")]
    broken = [f'{s["source"]}: {s.get("error", "")[:60]}' for s in data.get("sources", []) if not s.get("ok")]
    try:
        flags = mailer.rpc("recent_flags", {"days": 7}) or []
    except Exception as exc:
        flags = []; print("flags unavailable:", exc, file=sys.stderr)
    titles = {e["id"]: e["title"] for e in data["events"]}
    disc_path = HERE / "discovered.json"
    disc = json.loads(disc_path.read_text()) if disc_path.exists() else {"groups": []}
    week = (date.today() - timedelta(days=7)).isoformat()
    new_groups = [g for g in disc["groups"] if g.get("found", "") >= week]

    li = lambda items: "<ul>" + "".join(f"<li>{E(str(i))}</li>" for i in items) + "</ul>" if items else "<p>None.</p>"
    html = (f"<h2>The Lineup weekly check, {date.today():%b %d}</h2>"
            f"<p>{len(soon)} in-person events in the next 60 days. {len(data.get('sources', []))} sources tracked.</p>"
            f"<h3>Flagged by users this week ({len(flags)})</h3>"
            + li([f'{titles.get(f["event_id"], f["event_id"])}: {f["reason"]} x{f["n"]}' + (f' ({f["note"]})' if f.get("note") else "") for f in flags])
            + f"<h3>States with nothing in the next 60 days ({len(empty)})</h3>" + li(empty)
            + f"<h3>Thin states (1-2 events)</h3>" + li(thin)
            + f"<h3>New groups found by discovery ({len(new_groups)})</h3>"
            + li([f'{g["name"]} ({g["home"]}) meetup.com/{g["slug"]}' for g in new_groups])
            + "<p>Bad find? Add its slug to \"blocked\" in scraper/discovered.json.</p>"
            + f"<h3>Feeds that errored ({len(broken)})</h3>" + li(broken)
            + f"<h3>Tracked groups with nothing posted right now ({len(quiet)})</h3><p>{E(', '.join(quiet[:80]))}</p>")
    text = f"Weekly check: {len(flags)} flags, {len(empty)} empty states, {len(new_groups)} new groups, {len(broken)} broken feeds."
    if mailer.DRY:
        print(text); return
    mailer.http("https://api.resend.com/emails", {"from": mailer.FROM, "to": [to], "subject": f"Lineup weekly check: {len(flags)} flags, {len(new_groups)} new groups",
                "html": html, "text": text}, {"Authorization": f"Bearer {mailer.env('RESEND_API_KEY')}"})
    print("coverage: sent")


if __name__ == "__main__":
    main()
