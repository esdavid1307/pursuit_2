# Internship Company Discovery

This local Python tool scans current and historical Markdown internship listings and builds a persistent SQLite catalog of companies and their ATS boards. History matters because repositories commonly replace live application links with `Closed` or remove old rows entirely.

The initial configuration scans the Canadian Tech Internships repository and the active, inactive, off-season, and archived tables on the `dev` branch of `SimplifyJobs/Summer2027-Internships`. Both Markdown pipe tables and HTML tables are supported. It recognizes Greenhouse, Lever, Workday, Ashby, SmartRecruiters, Workable, Rippling, Oracle Recruiting, iCIMS, Jobvite, and Eightfold; every other valid job URL is retained as `unknown`.

The Canadian source replays every relevant commit. Simplify's bot-generated repository has tens of thousands of README commits and already preserves closed listings in dedicated files, so it uses `history_mode: "snapshot"`: all configured catalogs are scanned at the latest `dev` commit on first run and whenever that branch changes. This avoids millions of duplicate observations while retaining active, inactive, off-season, and archived listings.

`--winter-history` performs a separate, idempotent scan of one daily `README-Off-Season.md` snapshot from August through October 2025. It only accepts rows explicitly tagged `Winter 2026`, and adds that evidence to each matching company's exported `recruiting_history` array.

## Setup

Python 3 and the `git` command are required. There are currently no third-party Python packages.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`GITHUB_TOKEN` is optional for public repositories. When provided, it is sent as an HTTPS authorization header and is never added to the clone URL.

## Run

```bash
# First run, or an idempotent rescan of all history
python main.py --full

# Fetch and process only commits after the saved repository head
python main.py

# Write the compact downstream catalog
python main.py --export

# Mine the completed 2025 recruiting window for tagged Winter 2026 roles
python main.py --winter-history
```

The reusable blob-filtered bare Git clones are stored in `.repo-cache/`, the database is `companies.db`, and export output is `companies.json`. Snapshot sources use shallow clones until a targeted historical command needs older commits. A rewritten upstream history automatically causes a safe full upsert scan.

To add another source, append an entry containing `repo` and `files` to `REPOSITORIES` in `config.py`; no parser changes are needed.

The database separates canonical companies, their monitorable ATS boards, per-repository discovery provenance, raw job observations, and incremental sync checkpoints. `companies.json` contains one object per company with an `ats_boards` array and an explicit `ats_provider_known` tag. Unknown job boards are grouped by normalized company name and host, while every individual URL remains available in `job_observations`. Companies are never deleted merely because a listing disappears.
