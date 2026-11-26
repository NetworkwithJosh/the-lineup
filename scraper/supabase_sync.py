"""Push the current event list into Supabase so 'going' and connect rules can check real event times.
Runs only when SUPABASE_URL and SUPABASE_SERVICE_KEY are set (GitHub secrets). Otherwise does nothing."""
import json, os, sys, urllib.request

def main():
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("supabase sync: not configured, skipping"); return
    evs = json.load(open(os.path.join(os.path.dirname(__file__), "..", "site", "data", "events.json")))["events"]
    rows = [{"id": e["id"], "title": e["title"][:300], "starts_at": e["start"], "state": e.get("state") or None,
             "city": e.get("city") or None} for e in evs if e.get("status") != "cancelled"]
    for i in range(0, len(rows), 500):
        req = urllib.request.Request(f"{url}/rest/v1/events?on_conflict=id", data=json.dumps(rows[i:i+500]).encode(),
              method="POST", headers={"apikey": key, **({} if key.startswith("sb_") else {"Authorization": f"Bearer {key}"}), "Content-Type": "application/json",
              "Prefer": "resolution=merge-duplicates,return=minimal"})
        urllib.request.urlopen(req, timeout=60).read()
    print(f"supabase sync: upserted {len(rows)} events")

if __name__ == "__main__":
    try: main()
    except Exception as exc:  # never break the site refresh over this
        print("supabase sync failed:", exc, file=sys.stderr)
