# Internship Company Discovery

This local Python tool scans current and historical Markdown internship listings and builds a persistent SQLite catalog of company ATS configurations. History matters because repositories commonly replace live application links with `Closed` or remove old rows entirely.

The initial configuration scans `README.md` and `README-2026.md` in `negarprh/Canadian-Tech-Internships-2027`. It recognizes Greenhouse, Lever, and Workday; every other valid job URL is retained as `unknown`.

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

The database separates canonical ATS identities, per-repository discovery provenance, raw job observations, and incremental sync checkpoints. Companies are never deleted merely because a listing disappears.

