"""Command-line entry point for historical internship company discovery."""

from argparse import ArgumentParser
from dataclasses import dataclass, field
import os
import subprocess
import sys

from ats_parser import parse_ats
from config import BASE_DIR, DATABASE_PATH, EXPORT_PATH, GIT_TIMEOUT_SECONDS, REPOSITORIES, REPO_CACHE_DIR
from database import Database
from github_parser import GitRepository, load_dotenv, parse_markdown_tables


@dataclass
class RunStats:
    commits: int = 0
    rows: int = 0
    skipped: int = 0
    errors: int = 0
    new_ids: set[int] = field(default_factory=set)
    updated_ids: set[int] = field(default_factory=set)
    new_names: list[str] = field(default_factory=list)


def process_repository(db: Database, repo_config: dict, full: bool, token: str | None) -> RunStats:
    slug = repo_config["repo"]
    print(f"\nProcessing {slug}")
    git_repo = GitRepository(slug, repo_config["files"], REPO_CACHE_DIR, token, GIT_TIMEOUT_SECONDS)
    head = git_repo.prepare()
    saved_head = None if full else db.get_sync_head(slug)
    if saved_head and not git_repo.is_ancestor(saved_head, head):
        print("Warning: saved commit is not in the current history; performing a full upsert scan.")
        saved_head = None
    commits = git_repo.commits(head, saved_head)
    stats = RunStats(commits=len(commits))
    try:
        for index, sha in enumerate(commits, start=1):
            if index % 100 == 0:
                print(f"  Scanned {index}/{len(commits)} commits...")
            for document in git_repo.documents_at(sha):
                listings, skipped = parse_markdown_tables(document.content)
                stats.rows += len(listings)
                stats.skipped += skipped
                for listing in listings:
                    if not listing.apply_url:
                        continue
                    ats = parse_ats(listing.apply_url)
                    if not ats:
                        stats.skipped += 1
                        continue
                    company_id, created = db.record_listing(
                        listing, ats, slug, document.path, sha, document.committed_at
                    )
                    if created:
                        stats.new_ids.add(company_id)
                        if len(stats.new_names) < 5:
                            stats.new_names.append(listing.company)
                    elif company_id not in stats.new_ids:
                        stats.updated_ids.add(company_id)
        db.finish_sync(slug, head)
    except Exception:
        db.rollback()
        raise
    return stats


def print_summary(db: Database, stats: RunStats) -> None:
    counts = db.ats_counts()
    print(f"\nCommits scanned: {stats.commits:,}")
    print(f"Rows parsed: {stats.rows:,}")
    print(f"Rows/errors skipped: {stats.skipped:,}")
    print("\nUnique ATS configurations discovered:")
    for ats in ("greenhouse", "lever", "workday", "unknown"):
        print(f"{ats.title()}: {counts.get(ats, 0):,}")
    print(f"\nNew companies added: {len(stats.new_ids):,}")
    print(f"Existing companies updated: {len(stats.updated_ids):,}")
    print(f"Total companies in database: {db.total_companies():,}")
    if stats.new_names:
        print("New examples: " + ", ".join(stats.new_names))


def main() -> int:
    parser = ArgumentParser(description="Discover company ATS configurations from internship repository history.")
    parser.add_argument("--full", action="store_true", help="Rescan all configured history using idempotent upserts.")
    parser.add_argument("--export", action="store_true", help="Export the current company catalog to companies.json.")
    args = parser.parse_args()

    load_dotenv(BASE_DIR / ".env")
    token = os.getenv("GITHUB_TOKEN") or None
    if not token and not args.export:
        print("Warning: GITHUB_TOKEN is not set; public access works but GitHub restrictions may be tighter.")

    db = Database(DATABASE_PATH)
    try:
        if args.export:
            count = db.export_json(EXPORT_PATH)
            print(f"Exported {count:,} companies to {EXPORT_PATH}")
            return 0
        combined = RunStats()
        for repo_config in REPOSITORIES:
            stats = process_repository(db, repo_config, args.full, token)
            combined.commits += stats.commits
            combined.rows += stats.rows
            combined.skipped += stats.skipped
            combined.errors += stats.errors
            combined.new_ids.update(stats.new_ids)
            combined.updated_ids.update(stats.updated_ids)
            combined.new_names.extend(stats.new_names[: max(0, 5 - len(combined.new_names))])
        combined.updated_ids.difference_update(combined.new_ids)
        print_summary(db, combined)
        return 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        print(f"GitHub/Git error: {detail.strip()}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; the last incomplete repository was not checkpointed.", file=sys.stderr)
        return 130
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

