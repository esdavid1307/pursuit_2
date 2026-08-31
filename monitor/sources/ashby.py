"""Ashby public job board API adapter."""

import requests

from monitor.sources import Job, SourceError, request_json, target_value


def fetch_jobs(target, timeout: int, session: requests.Session | None = None) -> list[Job]:
    session = session or requests.Session()
    board = target_value(target, "ats_site") or target_value(target, "ats_identifier")
    if not board:
        raise SourceError("missing Ashby board name")
    data = request_json(session, "GET", f"https://api.ashbyhq.com/posting-api/job-board/{board}", timeout)
    jobs = []
    for item in data.get("jobs", []):
        if item.get("isListed") is False:
            continue
        locations = [item.get("location") or ""]
        locations += [(entry or {}).get("location") or "" for entry in item.get("secondaryLocations") or []]
        location = ", ".join(part for part in locations if part)
        jobs.append(Job(str(item.get("id")) if item.get("id") is not None else None,
                        target_value(target, "company"), item.get("title") or "Untitled role",
                        location, item.get("jobUrl") or item.get("applyUrl") or "", "ashby",
                        item.get("publishedAt")))
    return [job for job in jobs if job.url]
