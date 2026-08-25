"""SQLite persistence for ATS identities, sources, observations, and sync state."""

from pathlib import Path
import json
import re
import sqlite3

from ats_parser import ATSInfo
from github_parser import Listing


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    ats TEXT NOT NULL,
    ats_identifier TEXT,
    ats_host TEXT NOT NULL,
    ats_site TEXT,
    original_job_url TEXT NOT NULL,
    identity_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS company_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    source_repo TEXT NOT NULL,
    first_seen_commit TEXT NOT NULL,
    last_seen_commit TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(company_id, source_repo)
);
CREATE TABLE IF NOT EXISTS job_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    company_name_raw TEXT NOT NULL,
    role TEXT,
    location TEXT,
    job_url TEXT NOT NULL,
    date_posted TEXT,
    source_repo TEXT NOT NULL,
    source_file TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE(job_url, source_repo, commit_sha)
);
CREATE TABLE IF NOT EXISTS sync_state (
    source_repo TEXT PRIMARY KEY,
    last_processed_commit TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_companies_ats ON companies(ats);
CREATE INDEX IF NOT EXISTS idx_observations_company ON job_observations(company_id);
"""


def _name_score(name: str) -> tuple[int, int]:
    words = re.findall(r"[A-Za-z0-9]+", name)
    return (len(words), len(name))


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def get_sync_head(self, repo: str) -> str | None:
        row = self.connection.execute(
            "SELECT last_processed_commit FROM sync_state WHERE source_repo = ?", (repo,)
        ).fetchone()
        return row[0] if row else None

    def record_listing(self, listing: Listing, ats: ATSInfo, repo: str, source_file: str, sha: str, seen_at: str) -> tuple[int, bool]:
        row = self.connection.execute(
            "SELECT id, company_name FROM companies WHERE identity_key = ?", (ats.identity_key,)
        ).fetchone()
        created = row is None
        if created:
            cursor = self.connection.execute(
                """INSERT INTO companies
                   (company_name, ats, ats_identifier, ats_host, ats_site, original_job_url, identity_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (listing.company, ats.ats, ats.ats_identifier, ats.ats_host, ats.ats_site, ats.original_job_url, ats.identity_key),
            )
            company_id = int(cursor.lastrowid)
        else:
            company_id = int(row["id"])
            better_name = listing.company if _name_score(listing.company) > _name_score(row["company_name"]) else row["company_name"]
            self.connection.execute(
                "UPDATE companies SET company_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (better_name, company_id),
            )

        self.connection.execute(
            """INSERT INTO company_sources
               (company_id, source_repo, first_seen_commit, last_seen_commit, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(company_id, source_repo) DO UPDATE SET
                 first_seen_commit = CASE WHEN excluded.first_seen_at < first_seen_at THEN excluded.first_seen_commit ELSE first_seen_commit END,
                 first_seen_at = MIN(first_seen_at, excluded.first_seen_at),
                 last_seen_commit = CASE WHEN excluded.last_seen_at > last_seen_at THEN excluded.last_seen_commit ELSE last_seen_commit END,
                 last_seen_at = MAX(last_seen_at, excluded.last_seen_at)""",
            (company_id, repo, sha, sha, seen_at, seen_at),
        )
        self.connection.execute(
            """INSERT OR IGNORE INTO job_observations
               (company_id, company_name_raw, role, location, job_url, date_posted,
                source_repo, source_file, commit_sha, observed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_id, listing.company, listing.role, listing.location, ats.original_job_url,
             listing.date_posted, repo, source_file, sha, seen_at),
        )
        return company_id, created

    def finish_sync(self, repo: str, head: str) -> None:
        self.connection.execute(
            """INSERT INTO sync_state(source_repo, last_processed_commit) VALUES (?, ?)
               ON CONFLICT(source_repo) DO UPDATE SET
                 last_processed_commit = excluded.last_processed_commit,
                 updated_at = CURRENT_TIMESTAMP""",
            (repo, head),
        )
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def ats_counts(self) -> dict[str, int]:
        rows = self.connection.execute("SELECT ats, COUNT(*) AS count FROM companies GROUP BY ats").fetchall()
        return {row["ats"]: row["count"] for row in rows}

    def total_companies(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0])

    def export_json(self, path: Path) -> int:
        rows = self.connection.execute(
            """SELECT company_name AS company, ats, ats_identifier, ats_host, ats_site
               FROM companies ORDER BY lower(company_name), ats, identity_key"""
        ).fetchall()
        data = [dict(row) for row in rows]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return len(data)

