# Pursuit — internship discovery and alerting

Two cooperating services that find Canadian (and optionally US) tech internships and alert them to Discord in near-real time:

```
┌──────────────────────┐   data/companies.json   ┌──────────────────────┐
│  catalog/            │ ──────────────────────► │  monitor/            │
│  the data miner      │                         │  the alerting service│
│                      │                         │                      │
│  mines two GitHub    │                         │  polls every ATS     │
│  internship lists    │                         │  board directly      │
│  → companies + their │                         │  every 5–30 min,     │
│  ATS job boards      │                         │  filters titles +    │
│  (SQLite catalog)    │                         │  locations, alerts   │
└──────────────────────┘                         │  Discord webhooks    │
   runs every 4h on the VM                       └──────────────────────┘
   (catalog-refresh.timer)                          runs 24/7 on the VM
                                                    (job-monitor.service)
```

- **`catalog/`** scans current and historical Markdown listings from
  `negarprh/Canadian-Tech-Internships-2027` and `SimplifyJobs/Summer2027-Internships`
  (blob-filtered bare git mirrors in `.repo-cache/`), and maintains a SQLite catalog
  (`data/companies.db`) of companies, their ATS boards, and recruiting history.
  `--export` writes the compact contract file `data/companies.json`.
- **`monitor/`** imports that file as scan targets and polls each company's live job
  board through one adapter per provider (`monitor/sources/`): Greenhouse, Lever,
  Workday, Ashby, SmartRecruiters, Workable, Rippling, Oracle Cloud, iCIMS.
  New matching postings are queued durably in `data/jobs.db` and delivered to
  Discord — Canadian jobs to `DISCORD_WEBHOOK_URL`, US jobs to `DISCORD_WEBHOOK_URL_USA`.

## Setup

Python 3.11+ and the `git` CLI.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in the Discord webhook(s); GITHUB_TOKEN optional
```

## Run

```bash
# Build/refresh the company catalog, then export the contract file
.venv/bin/python -m catalog
.venv/bin/python -m catalog --export

# Catalog extras: --full (rescan all history), --winter-history (mine tagged Winter 2026 rows)

# Run the monitor
.venv/bin/python -m monitor              # scan forever (what the VM runs)
.venv/bin/python -m monitor --once       # one scan cycle
.venv/bin/python -m monitor --validate   # fetch every board without alerting
.venv/bin/python -m monitor --test-discord
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests
```

## Layout

```
catalog/    GitHub-list miner (config.py lists the source repos; add a repo there, no parser changes needed)
monitor/    ATS poller + Discord delivery (sources/ = one adapter per provider)
tests/      test_catalog.py + test_monitor.py
data/       runtime artifacts, never committed: companies.db, companies.json, jobs.db
deploy/     systemd units + setup script for the GCP VM (see deploy/README.md)
```

## Behavior notes

- Titles must contain an internship term and a software/tech term; with `CANADA_ONLY=true`
  (default) locations must match Canada — or the US when the USA webhook is set.
- A board's first-ever scan baselines existing jobs silently unless
  `SEND_EXISTING_ON_FIRST_RUN=true` / `USA_SEND_EXISTING_ON_FIRST_RUN=true`
  (enabled on the VM so newly discovered companies alert their current openings).
  **Never rebuild `data/jobs.db` with these flags on** — every current job would flood the channels.
- Notification delivery is rate-limit aware and retries failures with backoff.
