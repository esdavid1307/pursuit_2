"""Normalized SQLite persistence for companies, ATS boards, and observations."""

from pathlib import Path
import json
import re
import sqlite3

from ats_parser import ATSInfo, normalize_company_name
from github_parser import Listing

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS companies (
 id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT NOT NULL,
 normalized_name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS company_aliases (
 normalized_name TEXT PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 display_name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ats_boards (
 id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 ats TEXT NOT NULL, ats_provider_known INTEGER NOT NULL, ats_identifier TEXT, ats_host TEXT NOT NULL,
 ats_site TEXT, original_job_url TEXT NOT NULL, identity_key TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS company_sources (
 id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 source_repo TEXT NOT NULL, first_seen_commit TEXT NOT NULL, last_seen_commit TEXT NOT NULL,
 first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, UNIQUE(company_id, source_repo));
CREATE TABLE IF NOT EXISTS job_observations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 ats_board_id INTEGER NOT NULL REFERENCES ats_boards(id) ON DELETE CASCADE, company_name_raw TEXT NOT NULL,
 role TEXT, location TEXT, job_url TEXT NOT NULL, date_posted TEXT, source_repo TEXT NOT NULL,
 source_file TEXT NOT NULL, commit_sha TEXT NOT NULL, observed_at TEXT NOT NULL,
 UNIQUE(job_url, source_repo, commit_sha));
CREATE TABLE IF NOT EXISTS sync_state (
 source_repo TEXT PRIMARY KEY, last_processed_commit TEXT NOT NULL,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_boards_company ON ats_boards(company_id);
CREATE INDEX IF NOT EXISTS idx_boards_ats ON ats_boards(ats);
CREATE INDEX IF NOT EXISTS idx_observations_company ON job_observations(company_id);
"""


def _name_score(name: str) -> tuple[int, int]:
    return (len(re.findall(r"[A-Za-z0-9]+", name)), len(name))


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(companies)")}
        if "normalized_name" not in columns:
            self.connection.close()
            raise RuntimeError("Legacy database detected; move companies.db aside and run a new --full scan.")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def get_sync_head(self, repo: str) -> str | None:
        row = self.connection.execute(
            "SELECT last_processed_commit FROM sync_state WHERE source_repo = ?", (repo,)
        ).fetchone()
        return row[0] if row else None

    def _company_for(self, name: str, board_identity: str) -> tuple[int, bool]:
        normalized = normalize_company_name(name)
        board = self.connection.execute(
            "SELECT company_id FROM ats_boards WHERE identity_key = ?", (board_identity,)
        ).fetchone()
        if board:
            company_id = int(board[0])
            alias = self.connection.execute(
                "SELECT company_id FROM company_aliases WHERE normalized_name = ?", (normalized,)
            ).fetchone()
            if alias and int(alias[0]) != company_id:
                self._merge_company(int(alias[0]), company_id)
            self.connection.execute(
                "INSERT OR REPLACE INTO company_aliases(normalized_name, company_id, display_name) VALUES (?, ?, ?)",
                (normalized, company_id, name),
            )
            row = self.connection.execute("SELECT company_name FROM companies WHERE id = ?", (company_id,)).fetchone()
            if _name_score(name) > _name_score(row[0]):
                self.connection.execute(
                    "UPDATE companies SET company_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (name, company_id),
                )
            return company_id, False
        row = self.connection.execute(
            """SELECT c.id, c.company_name FROM company_aliases a
               JOIN companies c ON c.id=a.company_id WHERE a.normalized_name = ?""", (normalized,)
        ).fetchone()
        if row:
            company_id = int(row["id"])
            if _name_score(name) > _name_score(row["company_name"]):
                self.connection.execute(
                    "UPDATE companies SET company_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (name, company_id),
                )
            return company_id, False
        cursor = self.connection.execute(
            "INSERT INTO companies(company_name, normalized_name) VALUES (?, ?)", (name, normalized)
        )
        company_id = int(cursor.lastrowid)
        self.connection.execute(
            "INSERT INTO company_aliases(normalized_name, company_id, display_name) VALUES (?, ?, ?)",
            (normalized, company_id, name),
        )
        return company_id, True

    def _merge_company(self, source_id: int, target_id: int) -> None:
        """Merge an alias-created company after a shared ATS board proves identity."""
        for source in self.connection.execute(
            "SELECT * FROM company_sources WHERE company_id = ?", (source_id,)
        ).fetchall():
            self.connection.execute(
                """INSERT INTO company_sources
                   (company_id, source_repo, first_seen_commit, last_seen_commit, first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(company_id, source_repo) DO UPDATE SET
                    first_seen_commit=CASE WHEN excluded.first_seen_at < first_seen_at THEN excluded.first_seen_commit ELSE first_seen_commit END,
                    first_seen_at=MIN(first_seen_at, excluded.first_seen_at),
                    last_seen_commit=CASE WHEN excluded.last_seen_at > last_seen_at THEN excluded.last_seen_commit ELSE last_seen_commit END,
                    last_seen_at=MAX(last_seen_at, excluded.last_seen_at)""",
                (target_id, source["source_repo"], source["first_seen_commit"], source["last_seen_commit"],
                 source["first_seen_at"], source["last_seen_at"]),
            )
        self.connection.execute("DELETE FROM company_sources WHERE company_id = ?", (source_id,))
        self.connection.execute("UPDATE ats_boards SET company_id = ? WHERE company_id = ?", (target_id, source_id))
        self.connection.execute("UPDATE job_observations SET company_id = ? WHERE company_id = ?", (target_id, source_id))
        self.connection.execute("UPDATE company_aliases SET company_id = ? WHERE company_id = ?", (target_id, source_id))
        self.connection.execute("DELETE FROM companies WHERE id = ?", (source_id,))

    def record_listing(self, listing: Listing, ats: ATSInfo, repo: str, source_file: str, sha: str, seen_at: str) -> tuple[int, int, bool, bool]:
        company_id, company_created = self._company_for(listing.company, ats.identity_key)
        row = self.connection.execute("SELECT id FROM ats_boards WHERE identity_key = ?", (ats.identity_key,)).fetchone()
        board_created = row is None
        if board_created:
            cursor = self.connection.execute(
                """INSERT INTO ats_boards
                   (company_id, ats, ats_provider_known, ats_identifier, ats_host, ats_site, original_job_url, identity_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (company_id, ats.ats, int(ats.ats != "unknown"), ats.ats_identifier,
                 ats.ats_host, ats.ats_site, ats.original_job_url, ats.identity_key),
            )
            board_id = int(cursor.lastrowid)
        else:
            board_id = int(row["id"])
            self.connection.execute("UPDATE ats_boards SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (board_id,))
        self.connection.execute(
            """INSERT INTO company_sources
               (company_id, source_repo, first_seen_commit, last_seen_commit, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(company_id, source_repo) DO UPDATE SET
                first_seen_commit=CASE WHEN excluded.first_seen_at < first_seen_at THEN excluded.first_seen_commit ELSE first_seen_commit END,
                first_seen_at=MIN(first_seen_at, excluded.first_seen_at),
                last_seen_commit=CASE WHEN excluded.last_seen_at > last_seen_at THEN excluded.last_seen_commit ELSE last_seen_commit END,
                last_seen_at=MAX(last_seen_at, excluded.last_seen_at)""",
            (company_id, repo, sha, sha, seen_at, seen_at),
        )
        self.connection.execute(
            """INSERT OR IGNORE INTO job_observations
               (company_id, ats_board_id, company_name_raw, role, location, job_url, date_posted,
                source_repo, source_file, commit_sha, observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_id, board_id, listing.company, listing.role, listing.location, ats.original_job_url,
             listing.date_posted, repo, source_file, sha, seen_at),
        )
        return company_id, board_id, company_created, board_created

    def finish_sync(self, repo: str, head: str) -> None:
        self.connection.execute(
            """INSERT INTO sync_state(source_repo, last_processed_commit) VALUES (?, ?)
               ON CONFLICT(source_repo) DO UPDATE SET last_processed_commit=excluded.last_processed_commit,
               updated_at=CURRENT_TIMESTAMP""", (repo, head),
        )
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def ats_counts(self) -> dict[str, int]:
        return dict(self.connection.execute("SELECT ats, COUNT(*) FROM ats_boards GROUP BY ats").fetchall())

    def total_companies(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0])

    def company_ids(self) -> set[int]:
        return {int(row[0]) for row in self.connection.execute("SELECT id FROM companies")}

    def total_boards(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM ats_boards").fetchone()[0])

    def export_json(self, path: Path) -> int:
        companies = self.connection.execute(
            "SELECT id, company_name FROM companies ORDER BY lower(company_name), id"
        ).fetchall()
        data = []
        for company in companies:
            boards = self.connection.execute(
                """SELECT ats, ats_provider_known, ats_identifier, ats_host, ats_site, original_job_url
                   FROM ats_boards WHERE company_id=?
                   ORDER BY ats_provider_known DESC, ats, ats_host, coalesce(ats_site, '')""",
                (company["id"],),
            ).fetchall()
            data.append({"company": company["company_name"], "ats_boards": [
                {"ats": board["ats"], "ats_provider_known": bool(board["ats_provider_known"]),
                 "ats_identifier": board["ats_identifier"], "ats_host": board["ats_host"],
                 "ats_site": board["ats_site"], "original_job_url": board["original_job_url"]}
                for board in boards
            ]})
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return len(data)
