"""Greenhouse public board API adapter."""

import requests

from sources import Job, SourceError, request_json, target_value


def fetch_jobs(target, timeout: int, session: requests.Session | None = None) -> list[Job]:
    session = session or requests.Session()
    token = target_value(target, "ats_identifier") or target_value(target, "ats_site")
    if not token:
        raise SourceError("missing Greenhouse board token")
    data = request_json(session, "GET", f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", timeout)
    jobs = []
    for item in data.get("jobs", []):
        location = (item.get("location") or {}).get("name", "")
        jobs.append(Job(str(item.get("id")) if item.get("id") is not None else None,
                        target_value(target, "company"), item.get("title") or "Untitled role",
                        location, item.get("absolute_url") or "", "greenhouse", item.get("updated_at")))
    return [job for job in jobs if job.url]
