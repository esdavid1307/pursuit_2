"""Minute-wake scheduler and bounded concurrent board fetching."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import threading
import time

from database import Database
from filters import canada_first, is_canadian_location, is_relevant_job
from sources import ashby, greenhouse, lever, rippling, smartrecruiters, workable, workday


ADAPTERS = {
    "greenhouse": greenhouse.fetch_jobs,
    "lever": lever.fetch_jobs,
    "workday": workday.fetch_jobs,
    "ashby": ashby.fetch_jobs,
    "smartrecruiters": smartrecruiters.fetch_jobs,
    "workable": workable.fetch_jobs,
    "rippling": rippling.fetch_jobs,
}


@dataclass
class FetchResult:
    target: object
    jobs: list
    error: str | None = None


class Scheduler:
    def __init__(self, db: Database, settings, discord_client):
        self.db = db
        self.settings = settings
        self.discord = discord_client
        self._host_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._active: set[str] = set()
        self._active_lock = threading.Lock()

    def _fetch(self, target) -> FetchResult:
        key = target["target_key"]
        with self._active_lock:
            if key in self._active:
                return FetchResult(target, [], "target is already being checked")
            self._active.add(key)
        try:
            adapter = ADAPTERS[target["ats"]]
            host = target["ats_host"] or target["ats"]
            with self._host_locks[host.casefold()]:
                jobs = adapter(target, self.settings.request_timeout_seconds)
            return FetchResult(target, jobs)
        except Exception as exc:
            return FetchResult(target, [], str(exc))
        finally:
            with self._active_lock:
                self._active.discard(key)

    def fetch_targets(self, targets) -> list[FetchResult]:
        if not targets:
            return []
        results = []
        with ThreadPoolExecutor(max_workers=self.settings.max_workers, thread_name_prefix="ats") as pool:
            futures = [pool.submit(self._fetch, target) for target in targets]
            for future in as_completed(futures):
                results.append(future.result())
        return results

    def deliver_pending(self) -> tuple[int, int]:
        sent = failed = 0
        for row in self.db.pending_notifications():
            result = self.discord.send_job(row)
            if result.success:
                self.db.notification_sent(row["job_key"])
                sent += 1
                print(f"Discord sent: {row['title']} - {row['company']}")
                time.sleep(0.25)
            else:
                self.db.notification_failed(row["job_key"], result.error, result.retry_after_seconds)
                failed += 1
                print(f"Discord pending: {row['title']} - {result.error}")
        return sent, failed

    def run_due_scan(self) -> dict[str, int]:
        targets = self.db.due_targets()
        high = sum(target["priority"] == "high" for target in targets)
        print(f"[{datetime.now():%H:%M:%S}] Checking {len(targets)} due boards...")
        print(f"HIGH priority: {high}\nNORMAL priority: {len(targets) - high}")
        stats = {"targets": len(targets), "matched": 0, "new": 0, "queued": 0, "failed": 0}
        initial_saved = 0
        for result in self.fetch_targets(targets):
            target = result.target
            label = f"[{target['ats'].title()}] {target['company']}"
            if result.error:
                failures = self.db.record_failure(target, result.error)
                stats["failed"] += 1
                print(f"{label}: ERROR ({failures} failures): {result.error}")
                continue
            matches = [job for job in result.jobs if is_relevant_job(job.title)]
            if self.settings.canada_only:
                matches = [job for job in matches if is_canadian_location(job.location)]
            else:
                matches = canada_first(matches)
            stats["matched"] += len(matches)
            was_initialized = bool(target["initialized"])
            new, queued = self.db.record_success(
                target, matches, self.settings.send_existing_on_first_run
            )
            stats["new"] += new
            stats["queued"] += queued
            if not was_initialized and not self.settings.send_existing_on_first_run:
                initial_saved += new
            print(f"{label}: {len(result.jobs)} jobs fetched, {len(matches)} matching, {new} new")
        if initial_saved:
            print(f"Initial indexing complete: {initial_saved} existing matching jobs saved.")
        sent, pending = self.deliver_pending()
        print(f"Scan complete. Matching: {stats['matched']}; new: {stats['new']}; sent: {sent}; pending failures: {pending}")
        return stats

    def validate(self) -> dict[str, dict[str, int]]:
        targets = self.db.all_targets()
        summary = {name: {"valid": 0, "invalid": 0} for name in ADAPTERS}
        print(f"VALIDATING {len(targets)} ATS targets")
        for result in self.fetch_targets(targets):
            ats = result.target["ats"]
            if result.error:
                summary[ats]["invalid"] += 1
                print(f"INVALID [{ats.title()}] {result.target['company']} ({result.target['target_key']}): {result.error}")
            else:
                summary[ats]["valid"] += 1
        for ats, counts in summary.items():
            print(f"\n{ats.title()}:\nValid: {counts['valid']}\nInvalid: {counts['invalid']}")
        return summary

    def run_forever(self):
        while True:
            self.run_due_scan()
            time.sleep(self.settings.scheduler_wake_seconds)
