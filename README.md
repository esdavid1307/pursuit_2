# Internship Company Discovery

This local Python tool scans current and historical Markdown internship listings and builds a persistent SQLite catalog of companies and their ATS boards. History matters because repositories commonly replace live application links with `Closed` or remove old rows entirely.

The initial configuration scans `README.md` and `README-2026.md` in `negarprh/Canadian-Tech-Internships-2027`. It recognizes Greenhouse, Lever, Workday, Ashby, SmartRecruiters, Workable, Rippling, Oracle Recruiting, iCIMS, Jobvite, and Eightfold; every other valid job URL is retained as `unknown`.

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
```

The reusable bare Git mirrors are stored in `.repo-cache/`, the database is `companies.db`, and export output is `companies.json`. A rewritten upstream history automatically causes a safe full upsert scan.

To add another source, append an entry containing `repo` and `files` to `REPOSITORIES` in `config.py`; no parser changes are needed.

The database separates canonical companies, their monitorable ATS boards, per-repository discovery provenance, raw job observations, and incremental sync checkpoints. `companies.json` contains one object per company with an `ats_boards` array and an explicit `ats_provider_known` tag. Unknown job boards are grouped by normalized company name and host, while every individual URL remains available in `job_observations`. Companies are never deleted merely because a listing disappears.
