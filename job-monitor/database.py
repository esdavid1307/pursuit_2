"""SQLite scheduling, deduplication, and durable notification storage."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from sources import Job


SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_targets (
 target_key TEXT PRIMARY KEY, company TEXT NOT NULL, ats TEXT NOT NULL,
 ats_identifier TEXT, ats_host TEXT, ats_site TEXT, priority TEXT NOT NULL,
 poll_interval_minutes INTEGER NOT NULL, last_checked_at TEXT, last_success_at TEXT,
 last_job_seen_at TEXT, next_check_at TEXT, failure_count INTEGER NOT NULL DEFAULT 0,
 enabled INTEGER NOT NULL DEFAULT 1, initialized INTEGER NOT NULL DEFAULT 0,
 usa_initialized INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS seen_jobs (
 job_key TEXT PRIMARY KEY, source_job_id TEXT, company TEXT NOT NULL, ats TEXT NOT NULL,
 title TEXT NOT NULL, location TEXT, url TEXT NOT NULL, posted_at TEXT,
 first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
 job_key TEXT PRIMARY KEY REFERENCES seen_jobs(job_key) ON DELETE CASCADE,
 status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt_at TEXT NOT NULL, last_error TEXT, sent_at TEXT,
 region TEXT NOT NULL DEFAULT 'canada'
);
CREATE INDEX IF NOT EXISTS idx_targets_due ON monitor_targets(enabled, next_check_at);
CREATE INDEX IF NOT EXISTS idx_notifications_due ON notifications(status, next_attempt_at);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def target_key(board: dict) -> str | None:
    ats = str(board.get("ats", "")).casefold()
    identifier = str(board.get("ats_identifier") or "").strip()
    site = str(board.get("ats_site") or "").strip()
    host = str(board.get("ats_host") or "").strip().casefold()
    if ats in {"greenhouse", "lever", "ashby", "smartrecruiters", "workable", "rippling", "icims"} and (identifier or site):
        return f"{ats}:{(identifier or site).casefold()}"
    if ats == "workday" and host and identifier and site:
        return f"workday:{host}:{identifier.casefold()}:{site.casefold()}"
    if ats == "oracle" and host and site:
        return f"oracle:{host}:{site.casefold()}"
    return None


def job_key(job: Job) -> str:
    identity = job.source_job_id or hashlib.sha256(job.url.encode()).hexdigest()
    raw = f"{job.ats.casefold()}\0{job.company.casefold()}\0{identity}"
    return hashlib.sha256(raw.encode()).hexdigest()


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(SCHEMA)
        self._ensure_column("monitor_targets", "usa_initialized", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("notifications", "region", "TEXT NOT NULL DEFAULT 'canada'")
        self.connection.commit()

    def _ensure_column(self, table: str, column: str, definition: str):
        """CREATE TABLE IF NOT EXISTS never alters existing tables, so add new columns here."""
        existing = {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def close(self):
        self.connection.close()

    def import_targets(self, path: Path, high_minutes: int, normal_minutes: int) -> dict[str, int]:
        companies = json.loads(path.read_text(encoding="utf-8"))
        counts = {"high": 0, "normal": 0, "unsupported": 0}
        imported_keys: set[str] = set()
        now = iso(utc_now())
        for company in companies:
            high = any("winter" in str(item).casefold() for item in company.get("recruiting_history", []))
            priority = "high" if high else "normal"
            interval = high_minutes if high else normal_minutes
            for board in company.get("ats_boards", []):
                key = target_key(board) if board.get("ats_provider_known") else None
                if not key:
                    counts["unsupported"] += 1
                    continue
                if key not in imported_keys:
                    counts[priority] += 1
                    imported_keys.add(key)
                self.connection.execute(
                    """INSERT INTO monitor_targets
                       (target_key,company,ats,ats_identifier,ats_host,ats_site,priority,poll_interval_minutes,next_check_at)
                       VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(target_key) DO UPDATE SET company=excluded.company, ats=excluded.ats,
                        ats_identifier=excluded.ats_identifier, ats_host=excluded.ats_host,
                        ats_site=excluded.ats_site, priority=excluded.priority,
                        poll_interval_minutes=excluded.poll_interval_minutes""",
                    (key, company.get("company", "Unknown"), board.get("ats", "").casefold(),
                     board.get("ats_identifier"), board.get("ats_host"), board.get("ats_site"),
                     priority, interval, now),
                )
        self.connection.commit()
        return counts

    def due_targets(self, now: datetime | None = None) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM monitor_targets WHERE enabled=1 AND next_check_at<=? ORDER BY priority='high' DESC,next_check_at",
            (iso(now or utc_now()),),
        ).fetchall()

    def all_targets(self) -> list[sqlite3.Row]:
        return self.connection.execute("SELECT * FROM monitor_targets WHERE enabled=1 ORDER BY ats,company").fetchall()

    def is_seen(self, job: Job) -> bool:
        return self.connection.execute("SELECT 1 FROM seen_jobs WHERE job_key=?", (job_key(job),)).fetchone() is not None

    def record_success(self, target, jobs: list[Job], send_existing: bool, now: datetime | None = None,
                       regions: dict[str, str] | None = None, usa_active: bool = False,
                       usa_send_existing: bool = False) -> tuple[int, int]:
        now = now or utc_now()
        initialized = bool(target["initialized"])
        usa_initialized = bool(target["usa_initialized"])
        new_count = queued = 0
        with self.connection:
            for job in jobs:
                key = job_key(job)
                cursor = self.connection.execute(
                    """INSERT OR IGNORE INTO seen_jobs
                       (job_key,source_job_id,company,ats,title,location,url,posted_at,first_seen_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (key, job.source_job_id, job.company, job.ats, job.title, job.location,
                     job.url, job.posted_at, iso(now)),
                )
                if cursor.rowcount:
                    new_count += 1
                    region = regions.get(key, "canada") if regions else "canada"
                    if region == "usa":
                        should_queue = usa_initialized or usa_send_existing
                    else:
                        should_queue = initialized or send_existing
                    if should_queue:
                        self.connection.execute(
                            "INSERT OR IGNORE INTO notifications(job_key,next_attempt_at,region) VALUES (?,?,?)",
                            (key, iso(now), region),
                        )
                        queued += 1
            self.connection.execute(
                """UPDATE monitor_targets SET initialized=1,
                   usa_initialized=CASE WHEN ? THEN 1 ELSE usa_initialized END,
                   last_checked_at=?,last_success_at=?,
                   last_job_seen_at=CASE WHEN ?>0 THEN ? ELSE last_job_seen_at END,
                   next_check_at=?,failure_count=0 WHERE target_key=?""",
                (usa_active, iso(now), iso(now), len(jobs), iso(now), iso(now + timedelta(minutes=target["poll_interval_minutes"])), target["target_key"]),
            )
        return new_count, queued

    def record_failure(self, target, error: str, now: datetime | None = None) -> int:
        now = now or utc_now()
        failures = int(target["failure_count"]) + 1
        delay = int(target["poll_interval_minutes"])
        if failures == 2:
            delay = max(delay, 30)
        elif failures >= 3:
            delay = max(delay, 120)
        with self.connection:
            self.connection.execute(
                "UPDATE monitor_targets SET last_checked_at=?,next_check_at=?,failure_count=? WHERE target_key=?",
                (iso(now), iso(now + timedelta(minutes=delay)), failures, target["target_key"]),
            )
        return failures

    def pending_notifications(self, now: datetime | None = None, limit: int = 100) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT n.*,j.* FROM notifications n JOIN seen_jobs j USING(job_key)
               WHERE n.status='pending' AND n.next_attempt_at<=? ORDER BY j.first_seen_at LIMIT ?""",
            (iso(now or utc_now()), limit),
        ).fetchall()

    def notification_sent(self, key: str, now: datetime | None = None):
        with self.connection:
            self.connection.execute(
                "UPDATE notifications SET status='sent',sent_at=?,last_error=NULL WHERE job_key=?",
                (iso(now or utc_now()), key),
            )

    def notification_failed(self, key: str, error: str, retry_after_seconds: int = 60, now: datetime | None = None):
        now = now or utc_now()
        with self.connection:
            self.connection.execute(
                """UPDATE notifications SET attempts=attempts+1,last_error=?,next_attempt_at=? WHERE job_key=?""",
                (error[:1000], iso(now + timedelta(seconds=max(1, retry_after_seconds))), key),
            )

    def table_count(self, table: str) -> int:
        if table not in {"monitor_targets", "seen_jobs", "notifications"}:
            raise ValueError("invalid table")
        return int(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
