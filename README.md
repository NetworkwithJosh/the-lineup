# The Lineup

Cybersecurity, AI and IT meetups and conferences worldwide, refreshed every day. Tell it when you get off work and how long it takes you to get there, and it shows what you can actually make.

It only lists events other people organize. It does not run, host or sell tickets to anything.

## How it works

- `scraper/scrape.py` pulls public sources worldwide (ICS calendars like Black Hills Infosec, WiCyS, OpenSSF and conference feeds; Meetup groups; Luma calendars; the confs.tech open dataset), expands standing meetups from `recurring.json`, merges hand-checked events from `curated.json`, and writes `site/data/events.json` plus a subscribable feed at `site/lineup.ics`. Standard library only.
- Every run is compared with the last one. New events get a New tag, moved ones show what changed, and events that the organizer cancels (or that disappear from a working feed) show as Cancelled for up to 14 days. The calendar feed sends those cancellations too. If a source is down, its events are kept as they were and never marked cancelled.
- `site/index.html` is the whole site: the workday slider, filters, the board, and the feed link.
- `.github/workflows/refresh.yml` runs the scraper every morning and publishes the site to GitHub Pages.

## Run it locally

```bash
python scraper/scrape.py            # pulls feeds (needs internet)
python scraper/scrape.py --offline  # hand-checked + standing meetups only
python -m http.server 4500 -d site  # then open http://localhost:4500
```

## Add a source

- A Meetup group: add its URL slug to `meetup_groups` in `scraper/sources.json`.
- A Luma calendar: add its slug (the part after `luma.com/`) to `luma_calendars`.
- Any other calendar: add `{ "name": "...", "url": "https://...ics", "tags": ["cyber"], "region": "local" }` to `ics_urls`.
- A one-off conference: add it to `scraper/curated.json` with its source link.

Feeds that fail are skipped and listed in `events.json` under `sources`, so one dead feed never breaks the site.

## Publish on GitHub Pages

1. Create a repo named `the-lineup` and push this folder to `main`.
2. In the repo: Settings, Pages, Source: **GitHub Actions**.
3. Actions tab, "Refresh the lineup", **Run workflow**. The site goes live at `https://<your-username>.github.io/the-lineup/`.

Built with the scroll-craft design standard (live surface grammar).
