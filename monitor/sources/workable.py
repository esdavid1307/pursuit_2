"""Workable public widget API adapter."""

import requests

from monitor.sources import Job, SourceError, request_json, target_value


def fetch_jobs(target, timeout: int, session: requests.Session | None = None) -> list[Job]:
    session = session or requests.Session()
    account = target_value(target, "ats_site") or target_value(target, "ats_identifier")
    if not account:
        raise SourceError("missing Workable account name")
    data = request_json(session, "GET", f"https://apply.workable.com/api/v1/widget/accounts/{account}", timeout)
    jobs = []
    for item in data.get("jobs", []):
        location = ", ".join(part for part in (item.get("city"), item.get("state"), item.get("country")) if part)
        jobs.append(Job(item.get("shortcode"), target_value(target, "company"),
                        item.get("title") or "Untitled role", location, item.get("url") or "",
                        "workable", item.get("published_on")))
    return [job for job in jobs if job.url]
